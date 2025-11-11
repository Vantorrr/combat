import os
import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
from config import settings
from datetime import datetime


class GoogleSheetsService:
    def __init__(self):
        self.credentials = None
        self.service = None
        self._initialize_service()
        
    def _ensure_oauth_files(self) -> None:
        """Если переданы OAuth файлы через переменные окружения, восстанавливаем их на диск."""
        client_b64 = os.getenv("GOOGLE_OAUTH_CLIENT_JSON_B64")
        token_b64 = os.getenv("GOOGLE_OAUTH_TOKEN_JSON_B64")
        
        if client_b64:
            try:
                Path("oauth_client.json").write_bytes(base64.b64decode(client_b64))
            except Exception as e:
                logger.warning(f"Failed to decode GOOGLE_OAUTH_CLIENT_JSON_B64: {e}")
        
        if token_b64:
            try:
                Path("token.json").write_bytes(base64.b64decode(token_b64))
            except Exception as e:
                logger.warning(f"Failed to decode GOOGLE_OAUTH_TOKEN_JSON_B64: {e}")
        
    def _now_str(self) -> str:
        """Возвращает текущую дату с учётом часового пояса из настроек."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(getattr(settings, 'timezone', 'Europe/Moscow'))
        except Exception:
            tz = None
        if tz is not None:
            return datetime.now(tz).strftime('%d.%m.%y')
        return datetime.now().strftime('%d.%m.%y')
    
    def _initialize_service(self):
        """Инициализация сервиса Google Sheets.
        Если есть oauth_client.json/token.json — используем OAuth.
        Иначе — service account.
        """
        try:
            # При необходимости восстановить OAuth файлы из переменных окружения
            self._ensure_oauth_files()
            
            # Попытка через OAuth (приоритетнее)
            from services.google_sheets_oauth import oauth_client  # lazy import
            try:
                sheets_service = oauth_client.get_sheets_service()
                self.service = sheets_service
                self.credentials = oauth_client.creds
                logger.info("Google Sheets via OAuth")
                return
            except Exception as oauth_err:
                logger.warning(f"OAuth not configured, fallback to service account: {oauth_err}")

            # Fallback: service account
            # 1) Через переменную окружения GOOGLE_SERVICE_ACCOUNT_JSON (рекомендуется для Railway)
            sa_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            if sa_json_env:
                info = json.loads(sa_json_env)
                self.credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            else:
                # 2) Через файл по пути из настроек
                self.credentials = service_account.Credentials.from_service_account_file(
                    settings.google_sheets_credentials_file,
                    scopes=scopes
                )
            self.service = build('sheets', 'v4', credentials=self.credentials)
            logger.info("Google Sheets via Service Account")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {e}")
            raise

    def _get_first_sheet_gid(self, spreadsheet_id: str) -> int:
        """Получить gid первого листа (вместо предположения sheetId=0)."""
        meta = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = meta.get('sheets', [])
        if not sheets:
            raise RuntimeError("Spreadsheet has no sheets")
        return sheets[0]['properties']['sheetId']
    
    async def create_manager_sheet(self, manager_name: str) -> Optional[str]:
        """Создать новую таблицу для менеджера"""
        try:
            # Проверяем, используем ли OAuth
            if hasattr(self.credentials, 'token'):
                # OAuth - создаем напрямую
                spreadsheet_body = {
                    'properties': {
                        'title': f'CRM - {manager_name}'
                    }
                }
                
                spreadsheet = self.service.spreadsheets().create(
                    body=spreadsheet_body
                ).execute()
                
                new_sheet_id = spreadsheet.get('spreadsheetId')
            else:
                # Service Account - копируем шаблон
                drive_service = build('drive', 'v3', credentials=self.credentials)
                copy_response = drive_service.files().copy(
                    fileId=settings.manager_sheet_template_id,
                    body={'name': f'CRM - {manager_name}'}
                ).execute()
                
                new_sheet_id = copy_response.get('id')
            
            if new_sheet_id:
                # Настраиваем заголовки
                await self._setup_sheet_headers(new_sheet_id)
                
                logger.info(f"Created new sheet for {manager_name}: {new_sheet_id}")
                return new_sheet_id
            
            return None
            
        except HttpError as error:
            logger.error(f"An error occurred while creating sheet: {error}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating sheet: {e}")
            return None
    
    async def _setup_sheet_headers(self, sheet_id: str):
        """Настроить заголовки таблицы"""
        headers = [
            ["Наименование компании", "ИНН", "ФИО ЛПР", "Телефон", 
             "Дата звонка будущая", 
             "История звонков (все комментарии)",
             "Финансы (выручка прошлый год) тыс рублей", 
             "Финансы (выручка позапрошлый год) тыс рублей",
             "Капитал и резервы за прошлый год (тыс рублей)",
             "Основные средства за прошлый год (тыс рублей)",
             "Дебеторская задолженность за прошлый год (тыс рублей)",
             "Кредиторская задолженность за прошлый год (тыс рублей)",
             "Госконтракты, сумма заключенных за всё время", 
             "Арбитражи (активные, кол-во)",
             "Арбитражи (активные, сумма)",
             "Арбитражи (последний документ, дата)", 
             "Телефон", 
             "ОКПД (основной)", "Наименование ОКПД",
             "Дата первого звонка"
            ]
        ]
        
        request = {
            'values': headers
        }
        
        # Обновляем заголовки с запасом по ширине (A-AZ)
        self.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='A1:AZ1',
            valueInputOption='RAW',
            body=request
        ).execute()
        
        # Формат заголовков
        format_request = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': self._get_first_sheet_gid(sheet_id),
                        'startRowIndex': 0,
                        'endRowIndex': 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': {'red': 0.8, 'green': 0.8, 'blue': 0.8},
                            'textFormat': {'bold': True},
                            'horizontalAlignment': 'CENTER',
                            'wrapStrategy': 'WRAP'
                        }
                    },
                    'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,wrapStrategy)'
                }
            }]
        }
        
        # Скрываем финансовые/служебные колонки по умолчанию (не меняем индексы)
        hidden_columns = list(range(6, 12)) + list(range(12, 17))
        first_gid = self._get_first_sheet_gid(sheet_id)
        for col_index in hidden_columns:
            format_request['requests'].append({
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': first_gid,
                        'dimension': 'COLUMNS',
                        'startIndex': col_index,
                        'endIndex': col_index + 1
                    },
                    'properties': {
                        'hiddenByUser': True
                    },
                    'fields': 'hiddenByUser'
                }
            })
        
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body=format_request
        ).execute()
        # Применяем валютное форматирование к нужным колонкам:
        # G,H,I,J,K,L,M,O (с учётом удалённых "Регион" и "ОКВЭД*")
        gid = self._get_first_sheet_gid(sheet_id)
        self._apply_currency_format(sheet_id, gid, [6,7,8,9,10,11,12,14])

    def _apply_currency_format(self, spreadsheet_id: str, sheet_gid: int, column_indices: List[int]) -> None:
        """Применить формат валюты (₽) к указанным колонкам, начиная со 2-й строки."""
        requests = []
        for col in column_indices:
            requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_gid,
                        'startRowIndex': 1,  # со 2-й строки, заголовок не трогаем
                        'startColumnIndex': col,
                        'endColumnIndex': col + 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'numberFormat': {
                                'type': 'CURRENCY',
                                'pattern': '"₽" #,##0'
                            }
                        }
                    },
                    'fields': 'userEnteredFormat.numberFormat'
                }
            })
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()

    async def _setup_supervisor_headers(self, sheet_id: str):
        """Настроить заголовки сводной таблицы руководителя (с колонкой Менеджер)."""
        headers = [
            ["Наименование компании", "ИНН", "ФИО ЛПР", "Телефон", 
             "Дата звонка будущая", 
             "История звонков (все комментарии)",
             "Финансы (выручка прошлый год) тыс рублей", 
             "Финансы (выручка позапрошлый год) тыс рублей",
             "Капитал и резервы за прошлый год (тыс рублей)",
             "Основные средства за прошлый год (тыс рублей)",
             "Дебеторская задолженность за прошлый год (тыс рублей)",
             "Кредиторская задолженность за прошлый год (тыс рублей)",
             "Госконтракты, сумма заключенных за всё время", 
             "Арбитражи (активные, кол-во)",
             "Арбитражи (активные, сумма)",
             "Арбитражи (последний документ, дата)", 
             "Телефон", 
             "ОКПД (основной)", "Наименование ОКПД",
             "Дата первого звонка", "Менеджер"
            ]
        ]
        self.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='A1:U1',
            valueInputOption='RAW',
            body={'values': headers}
        ).execute()
        # Формат валюты для: G,H,I,J,K,L,M,O (после удаления Регион/ОКВЭД)
        gid = self._get_first_sheet_gid(sheet_id)
        self._apply_currency_format(sheet_id, gid, [6,7,8,9,10,11,12,14])

    async def delete_columns_by_titles(self, sheet_id: str, titles: List[str]) -> None:
        """Удалить колонки по заголовкам (точное совпадение названия).
        Делает безопасно: сначала определяет индексы, затем удаляет по убыванию индексов.
        """
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A1:AZ1'
            ).execute()
            headers_row = (result.get('values') or [[]])[0]
            to_delete_indices = []
            for idx, title in enumerate(headers_row):
                if title in titles:
                    to_delete_indices.append(idx)
            if not to_delete_indices:
                logger.info(f"No columns to delete in {sheet_id} for titles {titles}")
                return
            to_delete_indices.sort(reverse=True)
            gid = self._get_first_sheet_gid(sheet_id)
            requests = []
            for idx in to_delete_indices:
                requests.append({
                    'deleteDimension': {
                        'range': {
                            'sheetId': gid,
                            'dimension': 'COLUMNS',
                            'startIndex': idx,
                            'endIndex': idx + 1
                        }
                    }
                })
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={'requests': requests}
            ).execute()
            logger.info(f"Deleted columns {to_delete_indices} from {sheet_id}")
        except Exception as e:
            logger.error(f"Error deleting columns in {sheet_id}: {e}")

    async def _ensure_headers(self, sheet_id: str) -> None:
        """Проверяет заголовки листа менеджера и при несовпадении приводит к актуальному виду."""
        try:
            expected = [
                "Наименование компании", "ИНН", "ФИО ЛПР", "Телефон",
                "Дата звонка будущая",
                "История звонков (все комментарии)",
                "Финансы (выручка прошлый год) тыс рублей",
                "Финансы (выручка позапрошлый год) тыс рублей",
                "Капитал и резервы за прошлый год (тыс рублей)",
                "Основные средства за прошлый год (тыс рублей)",
                "Дебеторская задолженность за прошлый год (тыс рублей)",
                "Кредиторская задолженность за прошлый год (тыс рублей)",
                "Госконтракты, сумма заключенных за всё время",
                "Арбитражи (активные, кол-во)",
                "Арбитражи (активные, сумма)",
                "Арбитражи (последний документ, дата)",
                "Телефон",
                "ОКПД (основной)", "Наименование ОКПД",
                "Дата первого звонка"
            ]

            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A1:Z1'
            ).execute()
            current = (result.get('values') or [[]])[0]

            if current != expected:
                logger.info("Sheet headers mismatch detected — updating to the latest structure")
                await self._setup_sheet_headers(sheet_id)
        except Exception as e:
            logger.warning(f"Unable to verify/update headers: {e}")
    
    async def add_new_call(self, sheet_id: str, call_data: Dict[str, Any]) -> bool:
        """Добавить данные о новом звонке"""
        try:
            await self._ensure_headers(sheet_id)
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:AZ'
            ).execute()
            values = result.get('values', [])
            row_num = 2 if len(values) <= 1 else len(values) + 1
            # Префиксуем комментарий датой, чтобы история была читабельной
            comment_prefixed = call_data.get('comment', '')
            if comment_prefixed:
                comment_prefixed = f"[{self._now_str()}] {comment_prefixed}"
            new_row = [
                call_data.get('company_name', ''),  # A
                call_data.get('inn', ''),  # B
                call_data.get('contact_name', ''),  # C
                call_data.get('phone', ''),  # D
                call_data.get('next_call_date', ''),  # E
                comment_prefixed,  # F
                call_data.get('revenue', ''),  # G
                call_data.get('revenue_previous', ''),  # H
                call_data.get('capital', ''),  # I
                call_data.get('assets', ''),  # J
                call_data.get('debit', ''),  # K
                call_data.get('credit', ''),  # L
                call_data.get('gov_contracts', ''),  # M
                call_data.get('arbitration_open_count', ''),  # N
                call_data.get('arbitration_open_sum', ''),  # O
                call_data.get('arbitration_last_doc_date', ''),  # P
                call_data.get('phone', ''),  # Q (дубль)
                call_data.get('okpd', ''),  # R
                call_data.get('okpd_name', ''),  # S
                self._now_str()  # T
            ]
            request = {'values': [new_row]}
            self.service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f'A{row_num}:T{row_num}',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=request
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Error adding new call: {e}")
            return False
    
    async def update_repeat_call(self, sheet_id: str, inn: str, call_data: Dict[str, Any]) -> bool:
        """Обновить данные о повторном звонке"""
        try:
            # Ищем строку с нужным ИНН
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:AZ'
            ).execute()
            
            values = result.get('values', [])
            row_index = None
            
            for i, row in enumerate(values):
                if len(row) > 1 and row[1] == inn:  # ИНН в колонке B
                    row_index = i + 1
                    break
            
            if row_index is None:
                logger.error(f"Company with INN {inn} not found")
                return False
            
            # Получаем текущую историю комментариев
            current_row = values[row_index - 1]
            existing_comments = current_row[5] if len(current_row) > 5 else ''
            
            # Добавляем новый комментарий к истории
            raw_comment = call_data.get('comment', '')
            new_comment = f"[{self._now_str()}] {raw_comment}" if raw_comment else ""
            if existing_comments:
                # Добавляем новый комментарий в начало истории
                updated_comments = f"{new_comment}\n---\n{existing_comments}"
            else:
                updated_comments = new_comment
            
            # Обновляем данные
            updates = [
                {
                    'range': f'E{row_index}',  # Дата следующего звонка
                    'values': [[call_data.get('next_call_date', '')]]
                },
                {
                    'range': f'F{row_index}',  # История звонков
                    'values': [[updated_comments]]
                },
                # Финансы / поля из DataNewton
                {'range': f'G{row_index}', 'values': [[call_data.get('revenue', '')]]},
                {'range': f'H{row_index}', 'values': [[call_data.get('revenue_previous', '')]]},
                {'range': f'I{row_index}', 'values': [[call_data.get('capital', '')]]},
                {'range': f'J{row_index}', 'values': [[call_data.get('assets', '')]]},
                {'range': f'K{row_index}', 'values': [[call_data.get('debit', '')]]},
                {'range': f'L{row_index}', 'values': [[call_data.get('credit', '')]]},
                {'range': f'M{row_index}', 'values': [[call_data.get('gov_contracts', '')]]},
                {'range': f'N{row_index}', 'values': [[call_data.get('arbitration_open_count', '')]]},
                {'range': f'O{row_index}', 'values': [[call_data.get('arbitration_open_sum', '')]]},
                {'range': f'P{row_index}', 'values': [[call_data.get('arbitration_last_doc_date', '')]]},
                {'range': f'Q{row_index}', 'values': [[call_data.get('phone', '')]]},
                {'range': f'R{row_index}', 'values': [[call_data.get('okpd', '')]]},
                {'range': f'S{row_index}', 'values': [[call_data.get('okpd_name', '')]]},
            ]
            
            # Выполняем пакетное обновление
            body = {
                'valueInputOption': 'RAW',
                'data': updates
            }
            
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body=body
            ).execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating repeat call: {e}")
            return False
    
    async def get_today_calls(self, sheet_id: str) -> List[Dict[str, Any]]:
        """Получить список звонков на сегодня"""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:Z'
            ).execute()
            
            values = result.get('values', [])
            today = self._now_str()
            today_calls = []
            
            for i, row in enumerate(values[1:], start=2):  # Пропускаем заголовок
                if len(row) > 4 and row[4] == today:  # E: Дата следующего звонка
                    today_calls.append({
                        'row_number': i,
                        'company_name': row[0] if len(row) > 0 else '',
                        'inn': row[1] if len(row) > 1 else '',
                        'contact_name': row[2] if len(row) > 2 else '',
                        'phone': row[3] if len(row) > 3 else '',
                        'last_comment': row[5] if len(row) > 5 else ''
                    })
            
            return today_calls
            
        except Exception as e:
            logger.error(f"Error getting today calls: {e}")
            return []
    
    async def update_supervisor_sheet(self, manager_name: str, call_data: Dict[str, Any]):
        """Обновить сводную таблицу руководителя"""
        try:
            if not settings.supervisor_sheet_id:
                logger.warning("Supervisor sheet ID not configured")
                return
            # Обеспечиваем корректные заголовки с колонкой Менеджер
            try:
                self.service.spreadsheets().values().get(
                    spreadsheetId=settings.supervisor_sheet_id,
                    range='A1:Y1'
                ).execute()
            except Exception:
                pass
            await self._setup_supervisor_headers(settings.supervisor_sheet_id)
            result = self.service.spreadsheets().values().get(
                spreadsheetId=settings.supervisor_sheet_id,
                range='A:U'
            ).execute()
            values = result.get('values', [])
            next_row = 2 if len(values) < 2 else len(values) + 1
            company_row = None
            if len(values) > 1:
                for i in range(1, len(values)):
                    if len(values[i]) > 1 and values[i][1] == call_data.get('inn'):
                        company_row = i + 1
                        break
            current_date = self._now_str()
            if company_row:
                updates = []
                updates.append({'range': f'E{company_row}', 'values': [[call_data.get('next_call_date', '')]]})
                existing_comments = values[company_row - 1][5] if len(values[company_row - 1]) > 5 else ''
                new_comment = f"[{manager_name}] [{current_date}] {call_data.get('comment', '')}"
                updated_comments = f"{new_comment}\n---\n{existing_comments}" if existing_comments else new_comment
                updates.append({'range': f'F{company_row}', 'values': [[updated_comments]]})
                # Колонка менеджера убрана из структуры — не пишем в Y
                self.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=settings.supervisor_sheet_id,
                    body={'valueInputOption': 'RAW', 'data': updates}
                ).execute()
            else:
                row_data = [
                    call_data.get('company_name', ''),  # A
                    call_data.get('inn', ''),  # B
                    call_data.get('contact_name', ''),  # C
                    call_data.get('phone', ''),  # D
                    call_data.get('next_call_date', ''),  # E
                    f"[{manager_name}] [{current_date}] {call_data.get('comment', '')}",  # F
                    call_data.get('revenue', ''),  # G
                    call_data.get('revenue_previous', ''),  # H
                    call_data.get('capital', ''),  # I
                    call_data.get('assets', ''),  # J
                    call_data.get('debit', ''),  # K
                    call_data.get('credit', ''),  # L
                    call_data.get('gov_contracts', ''),  # M
                    call_data.get('arbitration_open_count', ''),  # N
                    call_data.get('arbitration_open_sum', ''),  # O
                    call_data.get('arbitration_last_doc_date', ''),  # P
                    call_data.get('phone', ''),  # Q
                    call_data.get('okpd', ''),  # R
                    call_data.get('okpd_name', ''),  # S
                    current_date,  # T
                    manager_name  # U
                ]
                self.service.spreadsheets().values().append(
                    spreadsheetId=settings.supervisor_sheet_id,
                    range='A:U',
                    valueInputOption='RAW',
                    body={'values': [row_data]}
                ).execute()
            logger.info(f"Updated supervisor sheet for {call_data.get('company_name')}")
        except Exception as e:
            logger.error(f"Error updating supervisor sheet: {e}")
            
    async def update_specific_columns(self, sheet_id: str, inn: str, updates: Dict[str, Any]) -> bool:
        """
        Обновить только определенные колонки в существующей строке таблицы.
        
        updates: dict с ключами 'column' (буква) и 'value' (значение)
        Пример: {'column': 'Q', 'value': '5'} для обновления колонки Q (Арбитражные дела)
        
        Это экономит токены - обновляем только нужные ячейки.
        """
        try:
            # Получаем все данные
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:Z'
            ).execute()
            
            values = result.get('values', [])
            
            # Ищем строку с нужным ИНН
            row_index = None
            for i, row in enumerate(values):
                if len(row) > 1 and row[1] == inn:
                    row_index = i + 1
                    break
            
            if row_index is None:
                logger.warning(f"Company with INN {inn} not found in sheet {sheet_id}")
                return False
            
            # Формируем запросы на обновление
            update_requests = []
            for col_letter, value in updates.items():
                update_requests.append({
                    'range': f'{col_letter}{row_index}',
                    'values': [[value]]
                })
            
            # Выполняем пакетное обновление
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'RAW', 'data': update_requests}
            ).execute()
            
            logger.info(f"Updated columns {list(updates.keys())} for INN {inn} in sheet {sheet_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating specific columns: {e}")
            return False


# Инициализация сервиса будет происходить при первом использовании
google_sheets_service = None

def get_google_sheets_service():
    global google_sheets_service
    if google_sheets_service is None:
        google_sheets_service = GoogleSheetsService()
    return google_sheets_service

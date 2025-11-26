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
    
    # --- Helpers ---
    @staticmethod
    def _col_letters(start_letter: str, count: int) -> List[str]:
        """Вернуть массив буквенных адресов колонок, начиная с заданной."""
        def to_index(letter: str) -> int:
            idx = 0
            for ch in letter.upper():
                idx = idx * 26 + (ord(ch) - ord('A') + 1)
            return idx
        def to_letter(index: int) -> str:
            s = ""
            while index > 0:
                index, rem = divmod(index - 1, 26)
                s = chr(rem + ord('A')) + s
            return s
        start_idx = to_index(start_letter)
        return [to_letter(start_idx + i) for i in range(count)]
        
    def _ensure_oauth_files(self) -> None:
        """
        Восстанавливаем OAuth файлы из переменных окружения ИЛИ из base64-файлов.
        """
        client_b64_env = os.getenv("GOOGLE_OAUTH_CLIENT_JSON_B64")
        token_b64_env = os.getenv("GOOGLE_OAUTH_TOKEN_JSON_B64")
        
        # 1. Пробуем восстановить oauth_client.json
        if client_b64_env:
            try:
                Path("oauth_client.json").write_bytes(base64.b64decode(client_b64_env))
            except Exception as e:
                logger.warning(f"Failed to decode GOOGLE_OAUTH_CLIENT_JSON_B64: {e}")
        elif os.path.exists("oauth_client.b64"):
            try:
                # Читаем base64 из файла, очищаем от пробелов/переносов
                b64_data = Path("oauth_client.b64").read_text().strip().replace("\n", "")
                Path("oauth_client.json").write_bytes(base64.b64decode(b64_data))
            except Exception as e:
                logger.warning(f"Failed to restore oauth_client.json from b64 file: {e}")

        # 2. Пробуем восстановить token.json
        if token_b64_env:
            try:
                Path("token.json").write_bytes(base64.b64decode(token_b64_env))
            except Exception as e:
                logger.warning(f"Failed to decode GOOGLE_OAUTH_TOKEN_JSON_B64: {e}")
        elif os.path.exists("token.b64"):
            try:
                b64_data = Path("token.b64").read_text().strip().replace("\n", "")
                Path("token.json").write_bytes(base64.b64decode(b64_data))
            except Exception as e:
                logger.warning(f"Failed to restore token.json from b64 file: {e}")
        
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
            # При необходимости восстановить OAuth файлы
            self._ensure_oauth_files()
            
            # Попытка через OAuth (приоритетнее)
            # Мы импортируем внутри метода, чтобы избежать циклических импортов, если они есть,
            # и чтобы не падать при старте, если модуля нет (хотя он есть).
            try:
                from services.google_sheets_oauth import oauth_client
                sheets_service = oauth_client.get_sheets_service()
                # Если oauth_client вернул сервис, значит токены есть и валидны (или обновлены)
                if sheets_service:
                    self.service = sheets_service
                    self.credentials = oauth_client.creds
                    logger.info("Google Sheets via OAuth (User Account)")
                    return
            except Exception as oauth_err:
                logger.warning(f"OAuth not configured or failed, fallback to service account: {oauth_err}")

            # Fallback: service account
            sa_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            if sa_json_env:
                info = json.loads(sa_json_env)
                self.credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            else:
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

    def set_spreadsheet_locale(self, spreadsheet_id: str, locale: str = 'ru_RU') -> None:
        """Установить локаль таблицы (например, 'ru_RU')."""
        try:
            request = {
                'requests': [
                    {
                        'updateSpreadsheetProperties': {
                            'properties': {
                                'locale': locale
                            },
                            'fields': 'locale'
                        }
                    }
                ]
            }
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=request
            ).execute()
            logger.info(f"Set locale {locale} for spreadsheet {spreadsheet_id}")
        except Exception as e:
            logger.error(f"Failed to set locale for {spreadsheet_id}: {e}")

    async def create_manager_sheet(self, manager_name: str) -> Optional[str]:
        """
        Создать новую таблицу для менеджера.
        Используем создание с нуля (не копирование), чтобы обойти квоту хранилища Service Account.
        """
        try:
            # 1. Создаем пустую таблицу
            spreadsheet_body = {
                'properties': {
                    'title': f'CRM - {manager_name}'
                }
            }
            
            spreadsheet = self.service.spreadsheets().create(
                body=spreadsheet_body
            ).execute()
            
            new_sheet_id = spreadsheet.get('spreadsheetId')
            
            if not new_sheet_id:
                raise RuntimeError("Failed to obtain new sheet ID")
            
            logger.info(f"Created new sheet for {manager_name}: {new_sheet_id}")

            # 2. Даем доступ (Share to anyone with link as Editor)
            # Чтобы ты мог открыть таблицу, созданную сервисным аккаунтом.
            try:
                drive_service = build('drive', 'v3', credentials=self.credentials)
                permission = {
                    'type': 'anyone',
                    'role': 'writer'
                }
                drive_service.permissions().create(
                    fileId=new_sheet_id,
                    body=permission,
                    fields='id'
                ).execute()
                logger.info(f"Shared sheet {new_sheet_id} with anyone (writer)")
            except Exception as e:
                logger.error(f"Failed to share sheet: {e}")

            # 3. Настраиваем локаль и заголовки
            self.set_spreadsheet_locale(new_sheet_id, 'ru_RU')
            await self._setup_sheet_headers(new_sheet_id)
            
            return new_sheet_id
            
        except HttpError as error:
            logger.error(f"An error occurred while creating sheet: {error}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating sheet: {e}")
            return None
    
    async def _setup_sheet_headers(self, sheet_id: str):
        """Настроить заголовки таблицы - АКТУАЛЬНАЯ СХЕМА"""
        headers = [
            [
                "Наименование компании",  # A
                "ИНН",  # B
                "ФИО ЛПР",  # C
                "Телефон",  # D
                "Дата звонка будущая",  # E
                "История звонков (все комментарии)",  # F
                "Финансы (выручка позапрошлый год) тыс рублей",  # G
                "Финансы (выручка прошлый год) тыс рублей",  # H
                "Чистая прибыль за прошлый год (тыс рублей)",  # I
                "Капитал и резервы за прошлый год (тыс рублей)",  # J
                "Основные средства за прошлый год (тыс рублей)",  # K
                "Дебеторская задолженность за прошлый год (тыс рублей)",  # L
                "Кредиторская задолженность за прошлый год (тыс рублей)",  # M
                "Госконтракты, сумма заключенных за всё время",  # N
                "ОКВЭД (основной)",  # O
                "Наименование ОКПД",  # P
                "Дата первого звонка",  # Q
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
        # G,H,I,J,K,L,M,N (финансы + госконтракты) - индексы 6-13
        gid = self._get_first_sheet_gid(sheet_id)
        self._apply_currency_format(sheet_id, gid, [6,7,8,9,10,11,12,13])

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
                                # #,##0 в русской локали даст 1 234 555.
                                'pattern': '#,##0" ₽"'
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

    async def update_supervisor_sheet(self, manager_name: str, call_data: Dict[str, Any]):
        """Обновить сводную таблицу руководителя"""
        try:
            if not settings.supervisor_sheet_id:
                logger.warning("Supervisor sheet ID not configured")
                return
            # Обеспечиваем корректные заголовки с колонкой Менеджер
            try:
                await self._setup_supervisor_headers(settings.supervisor_sheet_id)
            except Exception as e:
                logger.warning(f"Failed to setup supervisor headers: {e}")

            result = self.service.spreadsheets().values().get(
                spreadsheetId=settings.supervisor_sheet_id,
                range='A:R'
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
                    body={'valueInputOption': 'USER_ENTERED', 'data': updates}
                ).execute()
            else:
                row_data = [
                    call_data.get('company_name', ''),  # A
                    call_data.get('inn', ''),  # B
                    call_data.get('contact_name', ''),  # C
                    call_data.get('phone', ''),  # D
                    call_data.get('next_call_date', ''),  # E
                    f"[{manager_name}] [{current_date}] {call_data.get('comment', '')}",  # F
                    call_data.get('revenue_previous', ''),  # G (позапрошлый год)
                    call_data.get('revenue', ''),  # H (прошлый год)
                    call_data.get('net_profit', ''),  # I
                    call_data.get('capital', ''),  # J
                    call_data.get('assets', ''),  # K
                    call_data.get('debit', ''),  # L
                    call_data.get('credit', ''),  # M
                    call_data.get('gov_contracts', ''),  # N
                    call_data.get('okved_main', ''),  # O
                    call_data.get('okpd_name', ''),  # P
                    current_date,  # Q
                    manager_name  # R
                ]
                self.service.spreadsheets().values().append(
                    spreadsheetId=settings.supervisor_sheet_id,
                    range='A:R',
                    valueInputOption='USER_ENTERED',
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

    async def get_today_calls(self, sheet_id: str) -> List[Dict[str, Any]]:
        """Получить список звонков, запланированных на сегодня."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:AZ'
            ).execute()
            values = result.get('values', [])
            
            today = self._now_str()
            today_calls = []
            
            # Пропускаем заголовок
            if len(values) > 1:
                for row in values[1:]:
                    # ИНН - колонка B (index 1), Дата след. звонка - колонка E (index 4)
                    if len(row) > 4:
                        next_call_date = row[4].strip()
                        if next_call_date == today:
                            today_calls.append({
                                'company_name': row[0] if len(row) > 0 else 'Не указано',
                                'inn': row[1] if len(row) > 1 else 'Не указано',
                                'phone': row[3] if len(row) > 3 else 'Не указано',
                            })
                            
            return today_calls
            
        except Exception as e:
            logger.error(f"Error fetching today calls: {e}")
            return []

    async def add_new_call(self, sheet_id: str, call_data: Dict[str, Any]) -> bool:
        """Добавить данные о новом звонке (СТАРАЯ РАБОЧАЯ СХЕМА: по sheet_id)."""
        try:
            # Гарантируем корректные заголовки
            await self._setup_sheet_headers(sheet_id)

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
                call_data.get('revenue_previous', ''),  # G (позапрошлый год)
                call_data.get('revenue', ''),  # H (прошлый год)
                call_data.get('net_profit', ''),  # I
                call_data.get('capital', ''),  # J
                call_data.get('assets', ''),  # K
                call_data.get('debit', ''),  # L
                call_data.get('credit', ''),  # M
                call_data.get('gov_contracts', ''),  # N
                call_data.get('okved_main', ''),  # O
                call_data.get('okpd_name', ''),  # P
                self._now_str()  # Q
            ]

            request = {'values': [new_row]}
            self.service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f'A{row_num}:Q{row_num}',
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body=request
            ).execute()

            # Принудительно применяем формат валюты для финансовых колонок в новой строке
            # G(6) - N(13)
            gid = self._get_first_sheet_gid(sheet_id)
            requests = []
            for col_idx in range(6, 14):
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': gid,
                            'startRowIndex': row_num - 1,
                            'endRowIndex': row_num,
                            'startColumnIndex': col_idx,
                            'endColumnIndex': col_idx + 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '#,##0" ₽"'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                })
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={'requests': requests}
            ).execute()

            return True
        except Exception as e:
            logger.error(f"Error adding new call: {e}")
            return False

    async def update_repeat_call(self, sheet_id: str, inn: str, call_data: Dict[str, Any]) -> bool:
        """Обновить данные о повторном звонке (СТАРАЯ РАБОЧАЯ СХЕМА: по sheet_id и ИНН)."""
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

            # Обновляем данные - АКТУАЛЬНАЯ СХЕМА (без арбитражей, без ОКПД кода)
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
                {'range': f'G{row_index}', 'values': [[call_data.get('revenue_previous', '')]]},
                {'range': f'H{row_index}', 'values': [[call_data.get('revenue', '')]]},
                {'range': f'I{row_index}', 'values': [[call_data.get('net_profit', '')]]},
                {'range': f'J{row_index}', 'values': [[call_data.get('capital', '')]]},
                {'range': f'K{row_index}', 'values': [[call_data.get('assets', '')]]},
                {'range': f'L{row_index}', 'values': [[call_data.get('debit', '')]]},
                {'range': f'M{row_index}', 'values': [[call_data.get('credit', '')]]},
                {'range': f'N{row_index}', 'values': [[call_data.get('gov_contracts', '')]]},
                {'range': f'O{row_index}', 'values': [[call_data.get('okved_main', '')]]},
                {'range': f'P{row_index}', 'values': [[call_data.get('okpd_name', '')]]},
            ]

            body = {
                'valueInputOption': 'USER_ENTERED',
                'data': updates
            }

            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body=body
            ).execute()

            # Принудительно обновляем формат валюты для измененной строки
            # G(6) - N(13)
            gid = self._get_first_sheet_gid(sheet_id)
            requests = []
            for col_idx in range(6, 14):
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': gid,
                            'startRowIndex': row_index - 1,
                            'endRowIndex': row_index,
                            'startColumnIndex': col_idx,
                            'endColumnIndex': col_idx + 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '#,##0" ₽"'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                })
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={'requests': requests}
            ).execute()

            return True

        except Exception as e:
            logger.error(f"Error updating repeat call: {e}")
            return False


# Инициализация сервиса будет происходить при первом использовании
google_sheets_service = None

def get_google_sheets_service():
    global google_sheets_service
    if google_sheets_service is None:
        google_sheets_service = GoogleSheetsService()
    return google_sheets_service

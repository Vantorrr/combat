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
            try:
                from services.google_sheets_oauth import oauth_client
                sheets_service = oauth_client.get_sheets_service()
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
                "Дата последнего звонка",  # R - NEW
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

    async def update_supervisor_sheet(self, manager_name: str, call_data: Dict[str, Any], check_headers: bool = True):
        """Обновить сводную таблицу руководителя"""
        try:
            if not settings.supervisor_sheet_id:
                logger.warning("Supervisor sheet ID not configured")
                return
            # Обеспечиваем корректные заголовки с колонкой Менеджер (только если просят)
            if check_headers:
                try:
                    await self._setup_supervisor_headers(settings.supervisor_sheet_id)
                except Exception as e:
                    logger.warning(f"Failed to setup supervisor headers: {e}")

            result = self.service.spreadsheets().values().get(
                spreadsheetId=settings.supervisor_sheet_id,
                range='A:S' # Увеличили диапазон чтения
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
                # Обновляем дату последнего звонка в сводной таблице тоже? 
                # Логично, чтобы руководитель видел. Но мы не знаем индекс последней колонки точно, если там Менеджер.
                # У нас структура: A-Q + R(Менеджер). Теперь будет A-Q + R(Дата последнего) + S(Менеджер)?
                # Пока не будем ломать сводную сложной логикой, просто комментарии и дату.
                
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
                    # Нет колонки даты последнего звонка пока в сводной, оставляем как было
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
        """Обновить только определенные колонки в существующей строке таблицы."""
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
            # Учитываем таймзону
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(getattr(settings, 'timezone', 'Europe/Moscow'))
                today_date = datetime.now(tz).date()
            except Exception:
                today_date = datetime.now().date()
            
            logger.info(f"Fetching calls for {sheet_id} on date {today_date}")

            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:AZ'
            ).execute()
            values = result.get('values', [])
            
            today_calls = []
            
            # Пропускаем заголовок
            if len(values) > 1:
                for i, row in enumerate(values[1:], 2):
                    # ИНН - колонка B (index 1), Дата след. звонка - колонка E (index 4)
                    if len(row) > 4:
                        next_call_date_str = row[4].strip()
                        if not next_call_date_str:
                            continue
                            
                        # Пытаемся распарсить дату из ячейки
                        parsed_date = None
                        try:
                            # Пробуем формат DD.MM.YY
                            if len(next_call_date_str.split('.')[-1]) == 2:
                                parsed_date = datetime.strptime(next_call_date_str, "%d.%m.%y").date()
                            # Пробуем формат DD.MM.YYYY
                            elif len(next_call_date_str.split('.')[-1]) == 4:
                                parsed_date = datetime.strptime(next_call_date_str, "%d.%m.%Y").date()
                        except ValueError:
                            continue # Невалидная дата
                        
                        # Сравниваем даты
                        if parsed_date == today_date:
                            today_calls.append({
                                'company_name': row[0] if len(row) > 0 else 'Не указано',
                                'inn': row[1] if len(row) > 1 else 'Не указано',
                                'contact_name': row[2] if len(row) > 2 else '',
                                'phone': row[3] if len(row) > 3 else 'Не указано',
                                'comment': row[5] if len(row) > 5 else '',
                                'revenue': row[7] if len(row) > 7 else '',
                                'gov_contracts': row[13] if len(row) > 13 else '',
                            })
            
            logger.info(f"Found {len(today_calls)} calls for today")
            return today_calls
            
        except Exception as e:
            logger.error(f"Error fetching today calls: {e}")
            return []

    async def get_missed_calls(self, sheet_id: str) -> List[Dict[str, Any]]:
        """Получить список пропущенных звонков (недозвонов).
        Логика:
        1. Дата следующего звонка <= Сегодня.
        2. Дата последнего звонка (Col R) != Сегодня.
        """
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:R'  # Читаем до R включительно
            ).execute()
            values = result.get('values', [])
            
            if len(values) < 2:
                return []

            today = datetime.now().date()
            today_str = self._now_str() # DD.MM.YY
            missed_calls = []
            
            for row in values[1:]:
                if len(row) < 5: # Нужно хотя бы до E (дата звонка)
                    continue
                    
                next_call_date_str = row[4].strip()
                if not next_call_date_str:
                    continue
                    
                # Парсим дату следующего звонка
                try:
                    # Формат может быть DD.MM.YY или DD.MM.YYYY
                    if len(next_call_date_str.split('.')[-1]) == 2:
                        next_call_date = datetime.strptime(next_call_date_str, "%d.%m.%y").date()
                    else:
                        next_call_date = datetime.strptime(next_call_date_str, "%d.%m.%Y").date()
                except ValueError:
                    continue # Некорректная дата, пропускаем
                
                # Если дата в будущем - не интересно
                if next_call_date > today:
                    continue
                    
                # Проверяем дату последнего звонка (Col R - индекс 17)
                last_call_date_str = row[17].strip() if len(row) > 17 else ""
                
                # Проверяем историю звонков (Col F - индекс 5) на случай если R пустой
                # Ищем вхождение сегодняшней даты в начале строки комментария
                comments = row[5].strip() if len(row) > 5 else ""
                has_comment_today = comments.startswith(f"[{today_str}]") or comments.startswith(today_str)
                
                # Если последний звонок был сегодня (по R или по комментарию) - значит звонили
                if last_call_date_str == today_str or has_comment_today:
                    continue
                    
                # Если дошли сюда - значит дата звонка наступила (или прошла), а звонка сегодня не было
                missed_calls.append({
                    'company_name': row[0] if len(row) > 0 else 'Не указано',
                    'inn': row[1] if len(row) > 1 else 'Не указано',
                    'phone': row[3] if len(row) > 3 else 'Не указано',
                    'planned_date': next_call_date_str
                })
                            
            return missed_calls
            
        except Exception as e:
            logger.error(f"Error fetching missed calls: {e}")
            return []

    async def find_company_by_inn(self, sheet_id: str, inn: str) -> Optional[Dict[str, Any]]:
        """
        Ищет компанию по ИНН в Google Sheet и возвращает ее данные.
        Возвращает словарь с данными компании или None, если не найдена.
        
        Учитывает, что ИНН с ведущим нулём может храниться без него (Google Sheets 
        автоматически убирает ведущие нули у чисел).
        """
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:R'  # Читаем до R включительно
            ).execute()
            values = result.get('values', [])

            if not values or len(values) < 2:
                return None # Нет данных или только заголовки

            # Нормализуем искомый ИНН (убираем ведущие нули для сравнения)
            inn_normalized = inn.lstrip('0')
            
            for row_index, row in enumerate(values[1:], 1): # Пропускаем заголовки
                if len(row) > 1:
                    sheet_inn = str(row[1]).strip()
                    sheet_inn_normalized = sheet_inn.lstrip('0')
                    
                    # Сравниваем и полный ИНН, и без ведущих нулей
                    if sheet_inn == inn or sheet_inn_normalized == inn_normalized:
                        company_data = {
                            'row_index': row_index + 1, # Реальный номер строки в таблице
                            'company_name': row[0] if len(row) > 0 else '',
                            'inn': inn,  # Возвращаем оригинальный ИНН с нулём
                            'contact_name': row[2] if len(row) > 2 else '',
                            'phone': row[3] if len(row) > 3 else '',
                            'next_call_date': row[4] if len(row) > 4 else '',
                            'comment': row[5] if len(row) > 5 else '',
                            'revenue_previous': row[6] if len(row) > 6 else '',
                            'revenue': row[7] if len(row) > 7 else '',
                            'net_profit': row[8] if len(row) > 8 else '',
                            'capital': row[9] if len(row) > 9 else '',
                            'assets': row[10] if len(row) > 10 else '',
                            'debit': row[11] if len(row) > 11 else '',
                            'credit': row[12] if len(row) > 12 else '',
                            'gov_contracts': row[13] if len(row) > 13 else '',
                            'okved_main': row[14] if len(row) > 14 else '',
                            'okpd_name': row[15] if len(row) > 15 else '',
                            'first_call_date': row[16] if len(row) > 16 else '',
                            'last_call_date': row[17] if len(row) > 17 else '',
                        }
                        return company_data
            return None
        except Exception as e:
            logger.error(f"Error finding company by INN {inn} in sheet {sheet_id}: {e}")
            return None

    async def add_new_call(self, sheet_id: str, call_data: Dict[str, Any], check_headers: bool = True) -> bool:
        """Добавить данные о новом звонке (СТАРАЯ РАБОЧАЯ СХЕМА: по sheet_id)."""
        try:
            # Гарантируем корректные заголовки (только если просят)
            if check_headers:
                await self._setup_sheet_headers(sheet_id)

            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:AZ'
            ).execute()
            values = result.get('values', [])
            row_num = 2 if len(values) <= 1 else len(values) + 1

            # Префиксуем комментарий датой, если её ещё нет
            comment = call_data.get('comment', '')
            today_str = self._now_str()
            
            # Проверяем, начинается ли комментарий с даты [DD.MM.YY]
            import re
            has_date_prefix = False
            if comment:
                # Ищем паттерн [DD.MM.YY] или [DD.MM.YYYY] в начале
                match = re.match(r'^\[\d{2}\.\d{2}\.\d{2,4}\]', comment.strip())
                if match:
                    has_date_prefix = True
            
            if comment and not has_date_prefix:
                comment = f"[{today_str}] {comment}"
            elif not comment:
                comment = "" # Ensure it's not None

            # Дата первого звонка: приоритет из call_data, иначе сегодня
            first_call_date = call_data.get('first_call_date')
            if not first_call_date:
                first_call_date = self._now_str()

            # ИНН сохраняем как текст с апострофом, чтобы ведущие нули не терялись
            inn_value = call_data.get('inn', '')
            if inn_value and inn_value.startswith('0'):
                inn_value = f"'{inn_value}"  # Апостроф заставляет Google Sheets хранить как текст
            
            new_row = [
                call_data.get('company_name', ''),  # A
                inn_value,  # B - ИНН как текст
                call_data.get('contact_name', ''),  # C
                call_data.get('phone', ''),  # D
                call_data.get('next_call_date', ''),  # E
                comment,  # F
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
                first_call_date,  # Q - Дата первого звонка
                self._now_str(),  # R - Дата последнего звонка (NEW)
            ]

            request = {'values': [new_row]}
            self.service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f'A{row_num}:R{row_num}', # Расширили диапазон до R
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
            
            # Нормализуем искомый ИНН (убираем ведущие нули для сравнения)
            inn_normalized = inn.lstrip('0')

            for i, row in enumerate(values):
                if len(row) > 1:
                    sheet_inn = str(row[1]).strip()
                    sheet_inn_normalized = sheet_inn.lstrip('0')
                    # Сравниваем и полный ИНН, и без ведущих нулей
                    if sheet_inn == inn or sheet_inn_normalized == inn_normalized:
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
                {
                    'range': f'R{row_index}',  # Дата последнего звонка (NEW)
                    'values': [[self._now_str()]]
                }
            ]
            
            body = {
                'valueInputOption': 'USER_ENTERED',
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


# Инициализация сервиса будет происходить при первом использовании
google_sheets_service = None

def get_google_sheets_service():
    global google_sheets_service
    if google_sheets_service is None:
        google_sheets_service = GoogleSheetsService()
    return google_sheets_service

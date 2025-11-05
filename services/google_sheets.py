import os
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
    
    def _initialize_service(self):
        """Инициализация сервиса Google Sheets.
        Если есть oauth_client.json/token.json — используем OAuth.
        Иначе — service account.
        """
        try:
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
            self.credentials = service_account.Credentials.from_service_account_file(
                settings.google_sheets_credentials_file,
                scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            )
            self.service = build('sheets', 'v4', credentials=self.credentials)
            logger.info("Google Sheets via Service Account")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {e}")
            raise
    
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
             "Регион(+n часов к Москве)", "ОКВЭД", "ОКВЭД (основной)",
             "Госконтракты, сумма заключенных за всё время", 
             "Арбитражные дела, сумма активных арбитраж", 
             "Банкротство (да/нет)", "Телефон", "Почта", 
             "ОКПД (основной)", "Наименование ОКПД", "ОКВЭД, название",
             "Дата первого звонка"
            ]
        ]
        
        request = {
            'values': headers
        }
        
        # Обновляем заголовки (A-Z = 26 колонок)
        self.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='A1:Z1',
            valueInputOption='RAW',
            body=request
        ).execute()
        
        # Форматируем заголовки и скрываем колонки
        format_request = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': 0,
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
        
        # Добавляем запросы на скрытие колонок
        # Колонки для скрытия по умолчанию:
        #  - F–K (индексы 6–11): финансы
        #  - L–P (индексы 12–16): регион/ОКВЭД/контракты/арбитраж
        hidden_columns = list(range(6, 12)) + list(range(12, 17))
        
        for col_index in hidden_columns:
            format_request['requests'].append({
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': 0,
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

    async def _ensure_headers(self, sheet_id: str) -> None:
        """Проверяет заголовки листа менеджера и при несовпадении приводит к актуальному виду.
        Это предотвращает смещение значений по колонкам, если старый лист имеет иную структуру.
        """
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
                "Регион(+n часов к Москве)", "ОКВЭД", "ОКВЭД (основной)",
                "Госконтракты, сумма заключенных за всё время",
                "Арбитражные дела, сумма активных арбитраж",
                "Банкротство (да/нет)", "Телефон", "Почта",
                "ОКПД (основной)", "Наименование ОКПД", "ОКВЭД, название",
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
            # Гарантируем корректные заголовки перед записью
            await self._ensure_headers(sheet_id)
            # Получаем текущие данные
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:Z'
            ).execute()
            
            values = result.get('values', [])
            
            # Определяем строку для вставки
            if len(values) <= 1:  # Только заголовки или пустая таблица
                row_num = 2
            else:
                row_num = len(values) + 1
            
            # Формируем данные для вставки
            new_row = [
                call_data.get('company_name', ''),
                call_data.get('inn', ''),
                call_data.get('contact_name', ''),
                call_data.get('phone', ''),
                call_data.get('next_call_date', ''),
                call_data.get('comment', ''),  # История звонков - первый комментарий
                call_data.get('revenue', ''),
                call_data.get('revenue_previous', ''),
                call_data.get('capital', ''),
                call_data.get('assets', ''),
                call_data.get('debit', ''),
                call_data.get('credit', ''),
                call_data.get('region', ''),
                call_data.get('okved', ''),
                call_data.get('okved_main', ''),
                call_data.get('gov_contracts', ''),
                call_data.get('arbitration', ''),
                call_data.get('bankruptcy', ''),
                call_data.get('phone', ''),
                call_data.get('email', ''),
                call_data.get('okpd', ''),  # ОКПД (основной)
                call_data.get('okpd_name', ''),  # Наименование ОКПД
                call_data.get('okved_name', ''),  # ОКВЭД, название
                datetime.now().strftime('%d.%m.%y')  # Дата первого звонка
            ]
            
            request = {
                'values': [new_row]
            }
            
            self.service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f'A{row_num}:Z{row_num}',
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
                range='A:Z'
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
            new_comment = call_data.get('comment', '')
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
                }
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
            today = datetime.now().strftime('%d.%m.%y')
            today_calls = []
            
            for i, row in enumerate(values[1:], start=2):  # Пропускаем заголовок
                if len(row) > 5 and row[5] == today:  # Дата следующего звонка
                    today_calls.append({
                        'row_number': i,
                        'company_name': row[0] if len(row) > 0 else '',
                        'inn': row[1] if len(row) > 1 else '',
                        'contact_name': row[2] if len(row) > 2 else '',
                        'phone': row[3] if len(row) > 3 else '',
                        'last_comment': row[6] if len(row) > 6 else '',
                        'okved': row[16] if len(row) > 16 else ''
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
            
            # Получаем текущие данные
            result = self.service.spreadsheets().values().get(
                spreadsheetId=settings.supervisor_sheet_id,
                range='A:Z'
            ).execute()
            
            values = result.get('values', [])
            
            # Определяем строку для записи
            if len(values) < 2:
                # Добавляем заголовки если их нет
                await self._setup_sheet_headers(settings.supervisor_sheet_id)
                next_row = 2
            else:
                next_row = len(values) + 1
            
            # Проверяем существует ли уже компания в таблице
            company_row = None
            if len(values) > 1:
                for i in range(1, len(values)):
                    if len(values[i]) > 1 and values[i][1] == call_data.get('inn'):
                        company_row = i + 1
                        break
            
            # Подготавливаем данные для записи
            current_date = datetime.now().strftime('%d.%m.%y')
            
            if company_row:
                # Обновляем существующую запись
                updates = []
                
                # Обновляем дату последнего звонка
                updates.append({
                    'range': f'E{company_row}',
                    'values': [[call_data.get('next_call_date', '')]]
                })
                
                # Получаем текущую историю комментариев
                existing_comments = ''
                if len(values[company_row - 1]) > 5:
                    existing_comments = values[company_row - 1][5]
                
                # Добавляем новый комментарий с именем менеджера
                new_comment = f"[{manager_name}] {call_data.get('comment', '')}"
                if existing_comments:
                    updated_comments = f"{new_comment}\n---\n{existing_comments}"
                else:
                    updated_comments = new_comment
                
                # Обновляем историю комментариев
                updates.append({
                    'range': f'F{company_row}',
                    'values': [[updated_comments]]
                })
                
                # Обновляем менеджера
                updates.append({
                    'range': f'Y{company_row}',
                    'values': [[manager_name]]
                })
                
                # Применяем обновления
                self.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=settings.supervisor_sheet_id,
                    body={'valueInputOption': 'RAW', 'data': updates}
                ).execute()
                
            else:
                # Добавляем новую запись
                row_data = [
                    call_data.get('company_name', ''),  # A
                    call_data.get('inn', ''),  # B
                    call_data.get('contact_name', ''),  # C
                    call_data.get('phone', ''),  # D
                    call_data.get('next_call_date', ''),  # E
                    f"[{manager_name}] {call_data.get('comment', '')}",  # F - История звонков
                    call_data.get('revenue', ''),  # G - Финансы прошлый год
                    call_data.get('revenue_previous', ''),  # H - Финансы позапрошлый год
                    call_data.get('capital', ''),  # I - Капитал и резервы
                    call_data.get('assets', ''),  # J - Основные средства
                    call_data.get('debit', ''),  # K - Дебиторская задолженность
                    call_data.get('credit', ''),  # L - Кредиторская задолженность
                    call_data.get('region', ''),  # M - Регион
                    call_data.get('okved', ''),  # N - ОКВЭД
                    call_data.get('okved_main', ''),  # O - ОКВЭД основной
                    call_data.get('gov_contracts', ''),  # P - Госконтракты
                    call_data.get('arbitration', ''),  # Q - Арбитражные дела
                    call_data.get('bankruptcy', ''),  # R - Банкротство
                    call_data.get('phone', ''),  # S - Телефон (дубль)
                    call_data.get('email', ''),  # T - Почта
                    call_data.get('okpd', ''),  # U - ОКПД (основной)
                    call_data.get('okpd_name', ''),  # V - Наименование ОКПД
                    call_data.get('okved_name', ''),  # W - ОКВЭД, название
                    current_date,  # X - Дата первого звонка
                    manager_name  # Y - Менеджер
                ]
                
                self.service.spreadsheets().values().append(
                    spreadsheetId=settings.supervisor_sheet_id,
                    range='A:Y',
                    valueInputOption='RAW',
                    body={'values': [row_data]}
                ).execute()
            
            logger.info(f"Updated supervisor sheet for {call_data.get('company_name')}")
            
        except Exception as e:
            logger.error(f"Error updating supervisor sheet: {e}")
            # Не прерываем процесс при ошибке обновления сводной таблицы
    
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

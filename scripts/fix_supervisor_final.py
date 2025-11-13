"""
Финальная чистка сводной таблицы:
1. Удалить все столбцы "Комментарий 1-10"
2. Удалить дубль "ОКВЭД (основной)"
3. Оставить только один столбец "История звонков (все комментарии)"
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings
from services.google_sheets import GoogleSheetsService
from loguru import logger

def fix_supervisor_sheet():
    """Исправить сводную таблицу"""
    try:
        gs = GoogleSheetsService()
        sheet_id = settings.supervisor_sheet_id
        
        logger.info("Processing supervisor sheet...")
        
        # Получаем текущие заголовки
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A1:AZ1'
        ).execute()
        headers = result.get('values', [[]])[0] if result.get('values') else []
        
        logger.info(f"Current headers: {headers}")
        
        # Находим индексы столбцов для удаления
        columns_to_delete = []
        
        for idx, header in enumerate(headers):
            # Удаляем "Комментарий 1-10"
            if header.startswith("Комментарий ") and header.split()[-1].isdigit():
                columns_to_delete.append(idx)
                logger.info(f"Will delete column {idx}: {header}")
            # Удаляем дубль "ОКВЭД (основной)" (оставляем только первый)
            elif header == "ОКВЭД (основной)":
                # Проверяем, есть ли уже такой столбец раньше
                if "ОКВЭД (основной)" in headers[:idx]:
                    columns_to_delete.append(idx)
                    logger.info(f"Will delete duplicate OKVED column {idx}")
        
        # Удаляем столбцы (в обратном порядке, чтобы индексы не сбивались)
        columns_to_delete.sort(reverse=True)
        
        for col_idx in columns_to_delete:
            logger.info(f"Deleting column at index {col_idx}...")
            gs.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={
                    "requests": [{
                        "deleteDimension": {
                            "range": {
                                "sheetId": 0,
                                "dimension": "COLUMNS",
                                "startIndex": col_idx,
                                "endIndex": col_idx + 1
                            }
                        }
                    }]
                }
            ).execute()
            logger.info(f"Column {col_idx} deleted")
        
        # Устанавливаем финальные заголовки
        final_headers = [
            "Наименование компании",  # A
            "ИНН",  # B
            "ФИО ЛПР",  # C
            "Телефон",  # D
            "ОКПД (основной)",  # E
            "Дата звонка будущая",  # F
            "История звонков (все комментарии)",  # G
            "Финансы (выручка прошлый год) тыс рублей",  # H
            "Финансы (выручка позапрошлый год) тыс рублей",  # I
            "Капитал и резервы за прошлый год (тыс рублей)",  # J
            "Основные средства за прошлый год (тыс рублей)",  # K
            "Дебеторская задолженность за прошлый год (тыс рублей)",  # L
            "Кредиторская задолженность за прошлый год (тыс рублей)",  # M
            "Госконтракты, сумма заключенных за всё время",  # N
            "Арбитражные дела (кол-во активных)",  # O
            "Арбитражные дела (сумма активных)",  # P
            "Арбитражные дела (дата последнего документа)",  # Q
            "ОКВЭД (основной)",  # R
            "Наименование ОКПД",  # S
            "Дата первого звонка",  # T
            "Менеджер"  # U
        ]
        
        gs.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='A1:U1',
            valueInputOption='RAW',
            body={'values': [final_headers]}
        ).execute()
        logger.info("Headers updated")
        
        logger.info("✅ Supervisor sheet fixed!")
        
    except Exception as e:
        logger.error(f"❌ Error fixing supervisor sheet: {e}")

if __name__ == "__main__":
    fix_supervisor_sheet()


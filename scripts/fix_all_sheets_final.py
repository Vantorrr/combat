"""
Финальная миграция всех листов:
1. Удалить дубль "Телефон" (столбец Q)
2. Вернуть "ОКПД (основной)" между "Телефон" и "ОКВЭД (основной)"
3. Применить формат ₽ к G:O, M
4. Нормализовать числа в этих столбцах
5. Обновить заголовки
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings
from services.google_sheets import GoogleSheetsService
from loguru import logger

async def fix_sheet(gs: GoogleSheetsService, sheet_id: str, sheet_name: str):
    """Исправить один лист"""
    try:
        logger.info(f"Processing {sheet_name}...")
        
        # 1. Получаем текущие данные
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A1:Z1'
        ).execute()
        headers = result.get('values', [[]])[0] if result.get('values') else []
        
        logger.info(f"Current headers: {headers}")
        
        # 2. Удаляем дубль "Телефон" (столбец Q, индекс 16)
        if len(headers) > 16 and headers[16] == "Телефон":
            logger.info(f"Deleting duplicate 'Телефон' column Q...")
            gs.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={
                    "requests": [{
                        "deleteDimension": {
                            "range": {
                                "sheetId": 0,
                                "dimension": "COLUMNS",
                                "startIndex": 16,
                                "endIndex": 17
                            }
                        }
                    }]
                }
            ).execute()
            logger.info("Duplicate phone column deleted")
        
        # 3. Вставляем "ОКПД (основной)" между "Телефон" (D) и "ОКВЭД (основной)" (теперь E после удаления Q)
        # После удаления Q, структура: A-D (как было), E (был F), F (был G)...
        # Нам нужно вставить новый столбец после D (индекс 4)
        logger.info("Inserting 'ОКПД (основной)' column after 'Телефон'...")
        gs.service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "requests": [{
                    "insertDimension": {
                        "range": {
                            "sheetId": 0,
                            "dimension": "COLUMNS",
                            "startIndex": 4,
                            "endIndex": 5
                        }
                    }
                }]
            }
        ).execute()
        
        # 4. Устанавливаем заголовок для нового столбца E
        gs.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='E1',
            valueInputOption='RAW',
            body={'values': [['ОКПД (основной)']]}
        ).execute()
        logger.info("'ОКПД (основной)' column inserted")
        
        # 5. Обновляем все заголовки на финальные
        final_headers = [
            "Наименование компании",  # A
            "ИНН",  # B
            "ФИО ЛПР",  # C
            "Телефон",  # D
            "ОКПД (основной)",  # E (новый)
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
            "Дата первого звонка"  # T
        ]
        
        gs.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='A1:T1',
            valueInputOption='RAW',
            body={'values': [final_headers]}
        ).execute()
        logger.info("Headers updated")
        
        # 6. Применяем формат ₽ к столбцам H:P (индексы 7-15)
        logger.info("Applying currency format to H:P...")
        gs.service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "requests": [{
                    "repeatCell": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 1,
                            "startColumnIndex": 7,
                            "endColumnIndex": 16
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "NUMBER",
                                    "pattern": "#,##0\" ₽\""
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat"
                    }
                }]
            }
        ).execute()
        logger.info("Currency format applied")
        
        # 7. Нормализуем числа в этих столбцах (H:P)
        logger.info("Normalizing numbers in H:P...")
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='H2:P'
        ).execute()
        rows = result.get('values', [])
        
        if rows:
            normalized_rows = []
            for row in rows:
                normalized_row = []
                for cell in row:
                    if isinstance(cell, str):
                        # Убираем пробелы, ₽, запятые
                        cleaned = cell.replace(' ', '').replace('₽', '').replace(',', '').strip()
                        if cleaned and cleaned.replace('.', '').replace('-', '').isdigit():
                            try:
                                normalized_row.append(float(cleaned))
                            except:
                                normalized_row.append(cell)
                        else:
                            normalized_row.append(cell)
                    else:
                        normalized_row.append(cell)
                normalized_rows.append(normalized_row)
            
            gs.service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range='H2:P',
                valueInputOption='USER_ENTERED',
                body={'values': normalized_rows}
            ).execute()
            logger.info("Numbers normalized")
        
        logger.info(f"✅ {sheet_name} fixed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Error fixing {sheet_name}: {e}")

async def main():
    """Исправить все листы менеджеров и сводную"""
    gs = GoogleSheetsService()
    
    # Получаем все листы менеджеров из БД
    from models import database
    from models.database import Manager
    from sqlalchemy import select
    
    # Инициализируем БД
    await database.init_db(settings.database_url_effective)
    
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Manager))
        managers = result.scalars().all()
        
        logger.info(f"Found {len(managers)} managers")
        
        for manager in managers:
            if manager.google_sheet_id:
                await fix_sheet(gs, manager.google_sheet_id, f"Manager: {manager.full_name}")
        
        # Исправляем сводную таблицу
        logger.info("Fixing supervisor sheet...")
        await fix_sheet(gs, settings.supervisor_sheet_id, "Supervisor Sheet")
    
    logger.info("🎉 All sheets fixed!")

if __name__ == "__main__":
    asyncio.run(main())


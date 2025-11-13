"""
Применить финальную схему ко всем таблицам:
- Удалить столбцы арбитражей (3 шт)
- Удалить столбец "ОКПД (код)"
- Оставить только 16 столбцов A-P
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings
from services.google_sheets import GoogleSheetsService
from loguru import logger

async def apply_final_schema(gs: GoogleSheetsService, sheet_id: str, sheet_name: str):
    """Применить финальную схему к одному листу"""
    try:
        logger.info(f"Processing {sheet_name}...")
        
        # Получаем текущие заголовки
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A1:Z1'
        ).execute()
        headers = result.get('values', [[]])[0] if result.get('values') else []
        
        logger.info(f"Current headers count: {len(headers)}")
        
        # Находим столбцы для удаления
        columns_to_delete = []
        
        for idx, header in enumerate(headers):
            # Удаляем арбитражи
            if "арбитраж" in header.lower() and ("кол-во" in header.lower() or "сумма" in header.lower() or "дата" in header.lower()):
                columns_to_delete.append(idx)
                logger.info(f"Will delete column {idx}: {header}")
            # Удаляем ОКПД (код)
            elif header == "ОКПД (код)":
                columns_to_delete.append(idx)
                logger.info(f"Will delete column {idx}: {header}")
        
        # Удаляем столбцы (в обратном порядке)
        columns_to_delete.sort(reverse=True)
        gid = gs._get_first_sheet_gid(sheet_id)
        
        for col_idx in columns_to_delete:
            logger.info(f"Deleting column at index {col_idx}...")
            gs.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={
                    "requests": [{
                        "deleteDimension": {
                            "range": {
                                "sheetId": gid,
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
            "Дата звонка будущая",  # E
            "История звонков (все комментарии)",  # F
            "Финансы (выручка прошлый год) тыс рублей",  # G
            "Финансы (выручка позапрошлый год) тыс рублей",  # H
            "Капитал и резервы за прошлый год (тыс рублей)",  # I
            "Основные средства за прошлый год (тыс рублей)",  # J
            "Дебеторская задолженность за прошлый год (тыс рублей)",  # K
            "Кредиторская задолженность за прошлый год (тыс рублей)",  # L
            "Госконтракты, сумма заключенных за всё время",  # M
            "ОКВЭД (основной)",  # N
            "Наименование ОКПД",  # O
            "Дата первого звонка"  # P
        ]
        
        gs.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range='A1:P1',
            valueInputOption='RAW',
            body={'values': [final_headers]}
        ).execute()
        logger.info("Headers updated to final schema")
        
        logger.info(f"✅ {sheet_name} - final schema applied!")
        
    except Exception as e:
        logger.error(f"❌ Error processing {sheet_name}: {e}")

async def main():
    """Применить финальную схему ко всем листам"""
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
                await apply_final_schema(gs, manager.google_sheet_id, f"Manager: {manager.full_name}")
        
        # Применяем к сводной таблице
        logger.info("Applying final schema to supervisor sheet...")
        await apply_final_schema(gs, settings.supervisor_sheet_id, "Supervisor Sheet")
    
    logger.info("🎉 Final schema applied to all sheets!")

if __name__ == "__main__":
    asyncio.run(main())


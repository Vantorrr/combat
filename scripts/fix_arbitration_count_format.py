"""
Убрать формат ₽ из столбца "Арбитражи (кол-во активных)" - это штуки, не рубли
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings
from services.google_sheets import GoogleSheetsService
from loguru import logger

async def fix_arbitration_count_format(gs: GoogleSheetsService, sheet_id: str, sheet_name: str):
    """Убрать формат ₽ из столбца N (Арбитражи кол-во)"""
    try:
        logger.info(f"Processing {sheet_name}...")
        
        # Получаем заголовки
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A1:Z1'
        ).execute()
        headers = result.get('values', [[]])[0] if result.get('values') else []
        
        # Находим столбец "Арбитражи (кол-во активных)" или "Арбитражные дела (кол-во активных)"
        arb_count_col_idx = None
        for idx, header in enumerate(headers):
            if "кол-во активных" in header.lower() and "арбитраж" in header.lower():
                arb_count_col_idx = idx
                logger.info(f"Found arbitration count column at index {idx}: {header}")
                break
        
        if arb_count_col_idx is None:
            logger.warning(f"Arbitration count column not found in {sheet_name}")
            return
        
        # Убираем формат ₽, оставляем обычный числовой формат
        gid = gs._get_first_sheet_gid(sheet_id)
        gs.service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "requests": [{
                    "repeatCell": {
                        "range": {
                            "sheetId": gid,
                            "startRowIndex": 1,  # Со 2-й строки
                            "startColumnIndex": arb_count_col_idx,
                            "endColumnIndex": arb_count_col_idx + 1
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "NUMBER",
                                    "pattern": "#,##0"  # Обычное число без ₽
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat"
                    }
                }]
            }
        ).execute()
        logger.info(f"✅ {sheet_name}: Arbitration count format fixed")
        
    except Exception as e:
        logger.error(f"❌ Error fixing {sheet_name}: {e}")

async def main():
    """Исправить формат во всех листах"""
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
                await fix_arbitration_count_format(gs, manager.google_sheet_id, f"Manager: {manager.full_name}")
        
        # Исправляем сводную таблицу
        logger.info("Fixing supervisor sheet...")
        await fix_arbitration_count_format(gs, settings.supervisor_sheet_id, "Supervisor Sheet")
    
    logger.info("🎉 All sheets fixed!")

if __name__ == "__main__":
    asyncio.run(main())


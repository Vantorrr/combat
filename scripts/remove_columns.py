import os
import sys
import asyncio
from loguru import logger

# Ensure project root on sys.path
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import settings
from services.google_sheets import get_google_sheets_service
from models.database import init_db, get_session, Manager


async def run():
    await init_db(settings.database_url)
    gs = get_google_sheets_service()
    titles = ["Почта", "Банкротство (да/нет)"]

    # Удаляем в сводной таблице, если есть
    if settings.supervisor_sheet_id:
        logger.info("Deleting columns in supervisor sheet...")
        await gs.delete_columns_by_titles(settings.supervisor_sheet_id, titles)

    # Удаляем в таблицах менеджеров
    async for session in get_session():
        try:
            result = await session.execute(Manager.__table__.select())
            rows = result.fetchall()
            for row in rows:
                sheet_id = row.google_sheet_id if hasattr(row, 'google_sheet_id') else None
                if sheet_id:
                    logger.info(f"Deleting columns in manager sheet {sheet_id}...")
                    await gs.delete_columns_by_titles(sheet_id, titles)
        finally:
            await session.close()


if __name__ == "__main__":
    asyncio.run(run())



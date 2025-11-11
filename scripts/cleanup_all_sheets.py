import asyncio
from loguru import logger
import os

from config import settings
from models.database import init_db, get_session, Manager
from services.google_sheets import get_google_sheets_service
from scripts.fill_missing_finance import fill_sheet


async def process_manager_sheet(sheet_id: str):
    gs = get_google_sheets_service()
    # 1) Удаляем Region/OKVED на всякий случай
    await gs.delete_columns_by_titles(sheet_id, [
        "Регион(+n часов к Москве)", "ОКВЭД", "ОКВЭД (основной)", "ОКВЭД, название"
    ])
    # 2) Проставляем актуальные заголовки
    await gs._setup_sheet_headers(sheet_id)
    # 3) Формат валюты уже применяется внутри _setup_sheet_headers
    # 4) Добиваем финансы, если пусто
    await fill_sheet(sheet_id)


async def process_supervisor_sheet():
    gs = get_google_sheets_service()
    if not settings.supervisor_sheet_id:
        return
    # Удаляем Region/OKVED
    await gs.delete_columns_by_titles(settings.supervisor_sheet_id, [
        "Регион(+n часов к Москве)", "ОКВЭД", "ОКВЭД (основной)", "ОКВЭД, название"
    ])
    # Проставляем заголовки со столбцом Менеджер
    await gs._setup_supervisor_headers(settings.supervisor_sheet_id)


async def main():
    db_url = os.getenv("DATABASE_URL", settings.database_url_effective)
    await init_db(db_url)
    logger.info("DB connected")

    # Обрабатываем все таблицы менеджеров
    async for session in get_session():
        rows = (await session.execute(Manager.__table__.select())).fetchall()
        sheet_ids = [r.google_sheet_id for r in rows if getattr(r, "google_sheet_id", None)]
        logger.info(f"Found {len(sheet_ids)} manager sheets")
        for sid in sheet_ids:
            try:
                await process_manager_sheet(sid)
                logger.info(f"Processed manager sheet {sid}")
            except Exception as e:
                logger.warning(f"Failed to process {sid}: {e}")
        await session.close()

    await process_supervisor_sheet()
    logger.info("Supervisor sheet processed")


if __name__ == "__main__":
    asyncio.run(main())



import asyncio
from loguru import logger
from models.database import init_db, get_session, Manager
from services.google_sheets import get_google_sheets_service
from config import settings

COMMENT_TITLES = [f"Комментарий {i}" for i in range(1, 11)]


async def process_sheet(sheet_id: str):
    gs = get_google_sheets_service()
    await gs.delete_columns_by_titles(sheet_id, COMMENT_TITLES)
    logger.info(f"Removed comment columns from {sheet_id}")


async def main():
    await init_db(settings.database_url_effective)
    async for session in get_session():
        rows = (await session.execute(Manager.__table__.select())).fetchall()
        for row in rows:
            sid = getattr(row, "google_sheet_id", None)
            if sid:
                await process_sheet(sid)
        await session.close()
    # Supervisor
    if settings.supervisor_sheet_id:
        await process_sheet(settings.supervisor_sheet_id)


if __name__ == "__main__":
    asyncio.run(main())



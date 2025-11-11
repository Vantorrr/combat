import asyncio
from loguru import logger
from services.google_sheets import get_google_sheets_service
from config import settings


async def main():
    gs = get_google_sheets_service()
    titles = ["Регион(+n часов к Москве)", "ОКВЭД", "ОКВЭД (основной)", "ОКВЭД, название"]
    await gs.delete_columns_by_titles(settings.supervisor_sheet_id, titles)
    logger.info("Removed Region and OKVED columns from supervisor sheet")


if __name__ == "__main__":
    asyncio.run(main())



import asyncio
from loguru import logger
from services.google_sheets import get_google_sheets_service


async def remove_region(sheet_id: str):
    gs = get_google_sheets_service()
    await gs.delete_columns_by_titles(sheet_id, ["Регион(+n часов к Москве)"])
    logger.info(f"Removed 'Регион(+n часов к Москве)' from {sheet_id}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python scripts/remove_region_column.py <SHEET_ID>")
        raise SystemExit(1)
    asyncio.run(remove_region(sys.argv[1]))



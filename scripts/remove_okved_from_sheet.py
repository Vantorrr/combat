import asyncio
from loguru import logger
from services.google_sheets import get_google_sheets_service


async def remove_okved(sheet_id: str):
    gs = get_google_sheets_service()
    await gs.delete_columns_by_titles(sheet_id, ["ОКВЭД", "ОКВЭД (основной)", "ОКВЭД, название"])
    logger.info(f"Removed OKVED columns from {sheet_id}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python scripts/remove_okved_from_sheet.py <SHEET_ID>")
        raise SystemExit(1)
    asyncio.run(remove_okved(sys.argv[1]))



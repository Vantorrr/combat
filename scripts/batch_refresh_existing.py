import os
import sys
import asyncio
import re
from loguru import logger

# Ensure project root on sys.path
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from models.database import init_db, get_session, Manager
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api


def only_digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


async def refresh_manager_sheet(sheet_id: str) -> int:
    gs = get_google_sheets_service()
    # Ensure headers structure
    await gs._ensure_headers(sheet_id)

    # Read all values
    result = gs.service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range='A:AZ'
    ).execute()
    values = result.get('values', [])
    if len(values) <= 1:
        return 0

    updated = 0
    # Iterate rows starting from 2
    for i, row in enumerate(values[1:], start=2):
        inn = only_digits(row[1] if len(row) > 1 else "")
        if not inn:
            continue
        try:
            data = await datanewton_api.get_full_company_data(inn)
        except Exception as e:
            logger.warning(f"INN {inn}: fetch error: {e}")
            continue
        if not data:
            continue

        # Build updates map (column letter -> value)
        updates = {
            'G': data.get('revenue', ''),
            'H': data.get('revenue_previous', ''),
            'I': data.get('capital', ''),
            'J': data.get('assets', ''),
            'K': data.get('debit', ''),
            'L': data.get('credit', ''),
            'M': data.get('region', ''),
            'N': data.get('okved', ''),
            'O': data.get('okved', ''),
            'P': data.get('gov_contracts', ''),
            'Q': data.get('arbitration_open_count', ''),
            'R': data.get('arbitration_open_sum', ''),
            'S': data.get('arbitration_last_doc_date', ''),
            'U': data.get('okpd', ''),
            'V': data.get('okpd_name', ''),
            'W': data.get('okved_name', ''),
        }
        try:
            ok = await gs.update_specific_columns(sheet_id, inn, updates)
            if ok:
                updated += 1
        except Exception as e:
            logger.warning(f"INN {inn}: sheet update error: {e}")

        # Optional: small delay to be gentle on API
        await asyncio.sleep(0.1)

    return updated


async def run():
    await init_db("sqlite+aiosqlite:///./crmbot.db")
    total_updated = 0
    async for session in get_session():
        try:
            result = await session.execute(Manager.__table__.select())
            rows = result.fetchall()
            for row in rows:
                sheet_id = getattr(row, 'google_sheet_id', None)
                if not sheet_id:
                    continue
                logger.info(f"Refreshing sheet {sheet_id} ...")
                count = await refresh_manager_sheet(sheet_id)
                total_updated += count
                logger.info(f"Sheet {sheet_id}: updated {count} rows")
        finally:
            await session.close()
    logger.info(f"Batch refresh completed: total rows updated = {total_updated}")


if __name__ == "__main__":
    asyncio.run(run())




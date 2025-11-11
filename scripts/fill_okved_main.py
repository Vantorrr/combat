import asyncio
import re
from loguru import logger
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api


async def fill_okved(sheet_id: str):
    gs = get_google_sheets_service()
    # Ensure header has OKVED (main)
    await gs._setup_sheet_headers(sheet_id)
    resp = gs.service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range='A:U'
    ).execute()
    rows = resp.get('values', [])
    if len(rows) <= 1:
        return
    updates = []
    for idx, row in enumerate(rows[1:], start=2):
        inn = row[1] if len(row) > 1 else ''
        if not inn or not re.fullmatch(r'\\d{10}|\\d{12}', inn):
            continue
        current = row[17] if len(row) > 17 else ''  # R column
        if current:
            continue
        try:
            company = await datanewton_api.get_company_by_inn(inn)
            okved = (company or {}).get('okved', '')
        except Exception:
            okved = ''
        updates.append({'range': f'R{idx}', 'values': [[okved]]})
        if len(updates) >= 200:
            gs.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': updates}
            ).execute()
            updates.clear()
    if updates:
        gs.service.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={'valueInputOption': 'USER_ENTERED', 'data': updates}
        ).execute()
    logger.info("Filled OKVED (main)")


if __name__ == '__main__':
    import sys
    asyncio.run(fill_okved(sys.argv[1]))



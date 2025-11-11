import asyncio
import re
from loguru import logger

from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api


async def fill_sheet(sheet_id: str):
    gs = get_google_sheets_service()

    # Считываем всю таблицу
    result = gs.service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A:AZ"
    ).execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        logger.info("Sheet has no data rows")
        return

    header = rows[0]
    logger.info(f"Header columns: {len(header)}")

    updates_batch = []
    updated_count = 0

    for idx, row in enumerate(rows[1:], start=2):
        inn = row[1] if len(row) > 1 else ""
        if not inn or not re.fullmatch(r"\d{10}|\d{12}", inn):
            continue

        # Столбцы по схеме: I=капитал, J=основные, K=дебиторка, L=кредиторка
        capital = row[8] if len(row) > 8 else ""
        assets = row[9] if len(row) > 9 else ""
        debit = row[10] if len(row) > 10 else ""
        credit = row[11] if len(row) > 11 else ""

        # Пропускаем, если уже заполнены все три балансовых
        if assets and debit and credit:
            continue

        logger.info(f"Fetching finance for INN {inn} (row {idx})...")
        fin = await datanewton_api.get_finance_data(inn)

        updates_batch.extend([
            {'range': f'G{idx}', 'values': [[fin.get("revenue", "")]]},
            {'range': f'H{idx}', 'values': [[fin.get("revenue_previous", "")]]},
            {'range': f'I{idx}', 'values': [[capital or ""]]},  # капитал оставляем как есть, если пуст — не трогаем
            {'range': f'J{idx}', 'values': [[fin.get("assets", "")]]},
            {'range': f'K{idx}', 'values': [[fin.get("debit", "")]]},
            {'range': f'L{idx}', 'values': [[fin.get("credit", "")]]},
        ])
        updated_count += 1

        # Отправляем пачками по 100 строк
        if len(updates_batch) >= 600:
            gs.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': updates_batch}
            ).execute()
            updates_batch.clear()

    if updates_batch:
        gs.service.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={'valueInputOption': 'USER_ENTERED', 'data': updates_batch}
        ).execute()

    logger.info(f"Updated rows: {updated_count}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python scripts/fill_missing_finance.py <SHEET_ID>")
        sys.exit(1)
    asyncio.run(fill_sheet(sys.argv[1]))



from typing import List
from services.google_sheets import get_google_sheets_service
from loguru import logger
from config import settings


def apply_currency(spreadsheet_id: str, currency_columns: List[int]):
    gs = get_google_sheets_service()
    gid = gs._get_first_sheet_gid(spreadsheet_id)  # reuse helper
    # Build batch requests to set currency format '#,##0" ₽"'
    requests = []
    for col in currency_columns:
        requests.append({
            'repeatCell': {
                'range': {
                    'sheetId': gid,
                    'startRowIndex': 1,
                    'startColumnIndex': col,
                    'endColumnIndex': col + 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'numberFormat': {
                            'type': 'CURRENCY',
                            'pattern': '#,##0" ₽"'
                        }
                    }
                },
                'fields': 'userEnteredFormat.numberFormat'
            }
        })
    gs.service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': requests}
    ).execute()
    logger.info(f"Applied currency format to columns {currency_columns} on {spreadsheet_id}")


if __name__ == "__main__":
    # Manager sheet example
    # Manager columns after cleanup: G,H,I,J,K,L,M,O => indices 6,7,8,9,10,11,12,14
    manager_sheet_id = None
    import sys
    if len(sys.argv) >= 2:
        manager_sheet_id = sys.argv[1]
    if manager_sheet_id:
        apply_currency(manager_sheet_id, [6,7,8,9,10,11,12,14])
    # Supervisor
    try:
        if settings.supervisor_sheet_id:
            apply_currency(settings.supervisor_sheet_id, [6,7,8,9,10,11,12,14])
    except Exception:
        pass



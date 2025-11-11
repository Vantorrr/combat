import re
from typing import List
from loguru import logger
from services.google_sheets import get_google_sheets_service


def to_number(val: str):
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip()
    if not s:
        return ""
    # Удаляем все, кроме цифр и знака минус
    s = re.sub(r"[^\d\-]", "", s)
    try:
        return int(s)
    except Exception:
        return ""


def fix_sheet(spreadsheet_id: str, cols: List[str]):
    gs = get_google_sheets_service()
    result = gs.service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="A:Z"
    ).execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return
    # Map column letter to index (A=0)
    def col_idx(letter: str) -> int:
        return ord(letter.upper()) - ord('A')
    col_indices = [col_idx(c) for c in cols]

    updates = []
    for i, row in enumerate(rows[1:], start=2):
        for c, ci in zip(cols, col_indices):
            cur = row[ci] if len(row) > ci else ""
            num = to_number(cur)
            if num != "" and num != cur:
                updates.append({'range': f'{c}{i}', 'values': [[num]]})
    if updates:
        gs.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'valueInputOption': 'USER_ENTERED', 'data': updates}
        ).execute()
        logger.info(f"Fixed {len(updates)} currency cells on {spreadsheet_id}")
    else:
        logger.info("No currency cells to fix")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python scripts/fix_currency_cells.py <SHEET_ID>")
        raise SystemExit(1)
    # Финансовые и суммы: G,H,I,J,K,L,M,O
    fix_sheet(sys.argv[1], ["G","H","I","J","K","L","M","O"])



import asyncio
import os
import sys

# Добавляем корень проекта в sys.path
sys.path.append(os.getcwd())

from services.google_sheets import get_google_sheets_service

SHEET_ID = "1n1KGfZWz8qK6IIMsTnMs5qVXqUTmVmhMALK_DkIIyEM"

async def check_sheet_status():
    service = get_google_sheets_service()
    try:
        result = service.service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:A' # Читаем только первую колонку для подсчета строк
        ).execute()
        values = result.get('values', [])
        
        print(f"📊 В сводной таблице сейчас {len(values)} строк.")
        if len(values) > 0:
            print(f"🔹 Первая строка (заголовок): {values[0]}")
            print(f"🔹 Последняя строка: {values[-1]}")
            
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")

if __name__ == "__main__":
    asyncio.run(check_sheet_status())


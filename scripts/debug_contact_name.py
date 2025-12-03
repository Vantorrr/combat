import asyncio
import os
import sys

sys.path.append(os.getcwd())
from services.google_sheets import get_google_sheets_service

INN_TO_FIND = "1644023432"

async def debug_inn_search():
    service = get_google_sheets_service()
    
    # 1. Получаем список всех таблиц (файлов)
    drive_service = service.service_drive if hasattr(service, 'service_drive') else None
    if not drive_service:
        from googleapiclient.discovery import build
        drive_service = build('drive', 'v3', credentials=service.credentials)

    query = "mimeType='application/vnd.google-apps.spreadsheet' and name contains 'CRM -'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    print(f"🔍 Ищу ИНН {INN_TO_FIND} в {len(files)} таблицах...")
    
    for file in files:
        sheet_id = file['id']
        name = file['name']
        
        # Читаем таблицу
        try:
            res = service.service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range='A:D' # Нам нужны первые 4 колонки: A, B, C, D
            ).execute()
            values = res.get('values', [])
            
            for i, row in enumerate(values):
                if len(row) > 1 and str(row[1]).strip() == INN_TO_FIND:
                    print(f"\n✅ НАШЕЛ в таблице: {name} (ID: {sheet_id})")
                    print(f"Строка {i+1}: {row}")
                    
                    # Анализ колонки C (index 2)
                    if len(row) > 2:
                        contact_val = row[2]
                        print(f"Значение в колонке C (Contact): '{contact_val}' (len: {len(contact_val)})")
                        print(f"Repr: {repr(contact_val)}")
                    else:
                        print("⚠️ Колонка C отсутствует в этой строке!")
                    return
                    
        except Exception as e:
            print(f"⚠️ Ошибка чтения {name}: {e}")

    print("\n❌ ИНН не найден нигде.")

if __name__ == "__main__":
    asyncio.run(debug_inn_search())


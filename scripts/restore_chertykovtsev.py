import asyncio
import os
import sys

# Добавляем корень проекта в sys.path
sys.path.append(os.getcwd())

from services.google_sheets import get_google_sheets_service

from googleapiclient.discovery import build

async def find_chertykovtsev_sheet():
    service = get_google_sheets_service()
    
    # Инициализируем Drive API вручную
    drive_service = build('drive', 'v3', credentials=service.credentials)
    
    # Ищем файл через Drive API
    print("🔍 Ищу таблицу Чертыковцева...")
    
    # Запрос к Drive API
    query = "name contains 'Чертыковцев' and mimeType='application/vnd.google-apps.spreadsheet'"
    results = drive_service.files().list(
        q=query,
        fields="files(id, name)"
    ).execute()
    
    files = results.get('files', [])
    
    if not files:
        print("❌ Не нашел таблицу с именем 'Чертыковцев'.")
        return None
        
    for file in files:
        print(f"✅ Нашел: {file['name']} (ID: {file['id']})")
        return file['id']
        
    return None

async def copy_to_consolidated(source_id: str):
    CONSOLIDATED_ID = "1n1KGfZWz8qK6IIMsTnMs5qVXqUTmVmhMALK_DkIIyEM"
    service = get_google_sheets_service()
    
    print(f"📥 Копирую данные из {source_id} в сводную...")
    
    # Читаем исходную
    source_data = service.service.spreadsheets().values().get(
        spreadsheetId=source_id,
        range='A:AZ'
    ).execute().get('values', [])
    
    if not source_data:
        print("❌ Исходная таблица пуста")
        return

    print(f"📊 Строк в исходной: {len(source_data)}")
    
    # Чистим сводную
    service.service.spreadsheets().values().clear(
        spreadsheetId=CONSOLIDATED_ID,
        range='A:AZ'
    ).execute()
    
    # Записываем
    service.service.spreadsheets().values().update(
        spreadsheetId=CONSOLIDATED_ID,
        range='A1',
        valueInputOption='USER_ENTERED',
        body={'values': source_data}
    ).execute()
    
    print("✅ Данные успешно перенесены в сводную!")

if __name__ == "__main__":
    sheet_id = asyncio.run(find_chertykovtsev_sheet())
    if sheet_id:
        asyncio.run(copy_to_consolidated(sheet_id))


import asyncio
from services.google_sheets import get_google_sheets_service
from loguru import logger

async def find_sheet_by_name(name_part):
    service = get_google_sheets_service()
    # Using Drive API to search
    # We need to initialize Drive service separately or reuse credentials
    from googleapiclient.discovery import build
    
    print(f"Searching for sheet with name containing '{name_part}'...")
    
    drive_service = build('drive', 'v3', credentials=service.credentials)
    query = f"mimeType='application/vnd.google-apps.spreadsheet' and name contains '{name_part}' and trashed=false"
    
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if not files:
        print("No files found.")
    else:
        for file in files:
            print(f"Found: {file['name']} (ID: {file['id']})")
            
            # Now run the fix on this sheet
            await fix_sheet(service, file['id'], file['name'])

async def fix_sheet(service, sheet_id, name):
    import re
    print(f"Fixing sheet '{name}' ({sheet_id})...")
    try:
        result = service.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='F:F'
        ).execute()
        
        values = result.get('values', [])
        updates = []
        # Regex: matches [Date] followed optionally by newline/space, then Date, then optional " - "
        pattern = r'^\[(\d{2}\.\d{2}\.\d{2,4})\]\s*(?:\[?\1\]?|(?:\d{2}\.\d{2}\.\d{2,4}))\s*[-:]?\s*(.*)'
        
        for i, row in enumerate(values):
            if not row:
                continue
            original_text = row[0]
            if not original_text:
                continue
                
            match = re.match(pattern, original_text, re.DOTALL)
            if match:
                date_str = match.group(1)
                content = match.group(2)
                new_text = f"[{date_str}] {content}"
                
                if new_text != original_text:
                    updates.append({
                        'range': f'F{i+1}',
                        'values': [[new_text]]
                    })
        
        if updates:
            print(f"  Found {len(updates)} duplicates. Fixing...")
            service.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': updates}
            ).execute()
            print("  ✅ Fixed.")
        else:
            print("  No duplicates found.")
            
    except Exception as e:
        print(f"  ❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(find_sheet_by_name("Чертыковцев"))



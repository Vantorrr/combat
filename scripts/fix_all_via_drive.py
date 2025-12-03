import asyncio
import re
from services.google_sheets import get_google_sheets_service
from googleapiclient.discovery import build
from loguru import logger

# Configure logging
logger.add("fix_all_drive.log", rotation="1 MB")

async def fix_all_sheets_via_drive():
    print("🚀 Starting global fix via Google Drive API...")
    
    service = get_google_sheets_service()
    drive_service = build('drive', 'v3', credentials=service.credentials)
    
    # Search for all spreadsheets starting with "CRM -"
    # Note: 'name contains' is the best we can do, drive api doesn't support 'startswith' well for name
    query = "mimeType='application/vnd.google-apps.spreadsheet' and name contains 'CRM - ' and trashed=false"
    
    page_token = None
    total_fixed = 0
    
    while True:
        results = drive_service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name)",
            pageToken=page_token
        ).execute()
        
        files = results.get('files', [])
        
        for file in files:
            # Double check the name prefix just in case
            if not file['name'].strip().startswith("CRM -"):
                continue
                
            print(f"\nChecking sheet: {file['name']} ({file['id']})")
            try:
                await fix_sheet(service, file['id'], file['name'])
                total_fixed += 1
            except Exception as e:
                print(f"  ⚠️ Failed to check/fix {file['name']}: {e}")
                
        page_token = results.get('nextPageToken')
        if not page_token:
            break
            
    print(f"\n✅ Global fix completed. Checked {total_fixed} sheets.")

async def fix_sheet(service, sheet_id, name):
    # Read Column F (index 5)
    try:
        result = service.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='F:F'
        ).execute()
    except Exception as e:
        print(f"  ❌ Read error: {e}")
        return

    values = result.get('values', [])
    if not values:
        print("  (Empty sheet or no comments)")
        return

    updates = []
    # Regex to match:
    # [Date] [Date] ... or [Date] Date ...
    # It captures the first date, ensures the second date is effectively the same, and captures the rest
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
        print(f"  🔧 Found {len(updates)} duplicates. Fixing...")
        try:
            service.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': updates}
            ).execute()
            print("  ✅ Fixed.")
        except Exception as e:
             print(f"  ❌ Write error: {e}")
    else:
        print("  OK (No duplicates)")

if __name__ == "__main__":
    asyncio.run(fix_all_sheets_via_drive())



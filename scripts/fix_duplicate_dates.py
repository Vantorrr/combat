import asyncio
import re
from sqlalchemy import select
from models import database
from models.database import Manager
from services.google_sheets import get_google_sheets_service
from config import settings
from loguru import logger

# Configure simple logging
logger.add("fix_duplicates.log", rotation="1 MB")

async def fix_duplicate_dates():
    print("Starting duplicate date fix...")
    
    # Init DB
    await database.init_db(settings.database_url_effective)
    
    async with database.AsyncSessionLocal() as session:
        # Get all active managers
        result = await session.execute(select(Manager).where(Manager.is_active == True))
        managers = result.scalars().all()
        
        if not managers:
            print("No active managers found.")
            return

        sheets_service = get_google_sheets_service()
        
        for manager in managers:
            if not manager.google_sheet_id:
                continue
                
            print(f"\nProcessing {manager.full_name} (Sheet ID: {manager.google_sheet_id})...")
            
            try:
                # Read Column F (index 5)
                # We read F:F to get all comments
                result = sheets_service.service.spreadsheets().values().get(
                    spreadsheetId=manager.google_sheet_id,
                    range='F:F'
                ).execute()
                
                values = result.get('values', [])
                updates = []
                
                # Regex to find "[Date] Date" or "[Date] [Date]"
                pattern = r'^\[(\d{2}\.\d{2}\.\d{2,4})\]\s*(?:\[?\1\]?)\s*[-:]?\s*(.*)'
                
                for i, row in enumerate(values):
                    if not row:
                        continue
                    
                    original_text = row[0]
                    if not original_text:
                        continue
                        
                    # Apply regex
                    match = re.match(pattern, original_text, re.DOTALL)
                    
                    if match:
                        date_str = match.group(1)
                        content = match.group(2) # The rest of the comment
                        
                        new_text = f"[{date_str}] {content}"
                        
                        if new_text != original_text:
                            # print(f"  Fixing row {i+1}: '{original_text[:30]}...' -> '{new_text[:30]}...'")
                            updates.append({
                                'range': f'F{i+1}',
                                'values': [[new_text]]
                            })
                            
                if updates:
                    print(f"  Found {len(updates)} rows to fix. Applying updates...")
                    sheets_service.service.spreadsheets().values().batchUpdate(
                        spreadsheetId=manager.google_sheet_id,
                        body={'valueInputOption': 'USER_ENTERED', 'data': updates}
                    ).execute()
                    print("  ✅ Success.")
                else:
                    print("  No duplicate dates found.")
                    
            except Exception as e:
                print(f"  ❌ Error processing sheet: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(fix_duplicate_dates())
    except KeyboardInterrupt:
        print("Script interrupted.")
    except Exception as e:
        print(f"Script failed: {e}")

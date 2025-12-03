import asyncio
from services.google_sheets import get_google_sheets_service
from loguru import logger

# Configure logging
logger.add("debug_today_calls.log", rotation="1 MB")

async def debug_today_calls(manager_sheet_id):
    print(f"Debugging today's calls for sheet {manager_sheet_id}...")
    
    service = get_google_sheets_service()
    
    try:
        # Read all rows
        result = service.service.spreadsheets().values().get(
            spreadsheetId=manager_sheet_id,
            range='A:E' # Read up to E (Date)
        ).execute()
        
        values = result.get('values', [])
        today = service._now_str()
        print(f"Bot thinks today is: {today}")
        
        if not values:
            print("Sheet is empty.")
            return

        print(f"Found {len(values)} rows.")
        
        count = 0
        for i, row in enumerate(values):
            if i == 0: continue # Skip header
            
            # Check Column E (index 4)
            if len(row) > 4:
                date_val = row[4].strip()
                print(f"Row {i+1}: '{date_val}' (Expected format: DD.MM.YY)")
                
                if date_val == today:
                    print(f"  MATCH! This row should be in 'Today Calls'")
                    count += 1
                else:
                    # Check if it matches but maybe different year format
                    try:
                        # Try full year
                        from datetime import datetime
                        if len(date_val.split('.')[-1]) == 4:
                             dt = datetime.strptime(date_val, "%d.%m.%Y")
                             dt_today = datetime.strptime(today, "%d.%m.%y")
                             if dt.date() == dt_today.date():
                                 print(f"  MATCH (Full Year)! This row should be in 'Today Calls'")
                                 count += 1
                    except:
                        pass
            else:
                 print(f"Row {i+1}: No date in column E")

        print(f"\nTotal matches found by script: {count}")
        
        # Now run actual function
        calls = await service.get_today_calls(manager_sheet_id)
        print(f"Function returned {len(calls)} calls.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Use the sheet ID from screenshot or provided before
    # CRM - Чертыковцев Александр
    SHEET_ID = "1bvdlE9PxgZfGKWzIp2_w3vXN9cK5XJtswpnVP6744sQ" 
    asyncio.run(debug_today_calls(SHEET_ID))



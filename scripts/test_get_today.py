import asyncio
from services.google_sheets import get_google_sheets_service
from loguru import logger

# Configure logging
logger.add("test_get_today.log", rotation="1 MB")

async def test_get_today_calls():
    # SHEET_ID = "1bvdlE9PxgZfGKWzIp2_w3vXN9cK5XJtswpnVP6744sQ" # Чертыковцев Александр
    # Let's try to find a sheet ID that we know works or the one from user if possible.
    # Or just use the one we debugged before.
    SHEET_ID = "1bvdlE9PxgZfGKWzIp2_w3vXN9cK5XJtswpnVP6744sQ"
    
    print(f"Testing get_today_calls for sheet {SHEET_ID}...")
    service = get_google_sheets_service()
    
    try:
        calls = await service.get_today_calls(SHEET_ID)
        print(f"Success! Found {len(calls)} calls.")
        for call in calls:
            print(f" - {call}")
    except Exception as e:
        print(f"FAILED with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_get_today_calls())



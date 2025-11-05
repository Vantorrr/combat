import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.google_sheets_oauth import oauth_client

def main():
    # Прогреваем авторизацию и сохраняем token.json
    sheets = oauth_client.get_sheets_service()
    drive = oauth_client.get_drive_service()
    print("✅ OAuth настроен. token.json сохранен.")

if __name__ == "__main__":
    main()



from google_auth_oauthlib.flow import InstalledAppFlow
import os

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def authenticate():
    if not os.path.exists('oauth_client.json'):
        print("❌ Ошибка: файл oauth_client.json не найден!")
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        'oauth_client.json',
        SCOPES
    )
    
    print("Открываю браузер для авторизации...", flush=True)
    # Используем run_console для возможности скопировать код вручную
    creds = flow.run_console()
    
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
        
    print("\n✅ Авторизация успешна! Файл token.json создан.", flush=True)

if __name__ == '__main__':
    authenticate()

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
        SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )
    
    auth_url, _ = flow.authorization_url(prompt='consent')

    print("\n👇 ПЕРЕЙДИТЕ ПО ЭТОЙ ССЫЛКЕ И АВТОРИЗУЙТЕСЬ 👇\n")
    print(auth_url)
    print("\n👆 👆 👆\n")
    
    code = input("Введите код авторизации (скопируйте его со страницы): ")
    
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
        
    print("\n✅ Авторизация успешна! Файл token.json создан.", flush=True)

if __name__ == '__main__':
    authenticate()


"""
Запускать на Railway Shell:
python scripts/save_token_from_code.py <AUTH_CODE>
"""
import sys, json, base64, os
from datetime import datetime

code = sys.argv[1] if len(sys.argv) > 1 else input("Введи код: ").strip()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Читаем client config
b64_file = 'oauth_client.b64'
if os.path.exists(b64_file):
    b64_data = open(b64_file).read().strip()
    client_config = json.loads(base64.b64decode(b64_data))
else:
    # Пробуем из env
    b64_env = os.getenv('GOOGLE_OAUTH_CLIENT_JSON_B64') or os.getenv('GOOGLE_OAUTH_CLIENT_JSON_BASE64')
    if not b64_env:
        print("❌ Не найден oauth_client.b64 и нет env переменной!")
        sys.exit(1)
    client_config = json.loads(base64.b64decode(b64_env))

flow = InstalledAppFlow.from_client_config(
    client_config,
    scopes=SCOPES,
    redirect_uri='urn:ietf:wg:oauth:2.0:oob'
)

flow.fetch_token(code=code)
creds = flow.credentials
print(f'✅ Токен получен! Expiry: {creds.expiry}')

new_data = {
    'token': creds.token,
    'refresh_token': creds.refresh_token,
    'token_uri': creds.token_uri,
    'client_id': creds.client_id,
    'client_secret': creds.client_secret,
    'scopes': list(creds.scopes) if creds.scopes else list(SCOPES),
    'expiry': creds.expiry.isoformat() if creds.expiry else None
}

# Сохраняем в БД
import psycopg2
db_url = os.getenv('DATABASE_URL', '').replace('postgresql://', 'postgresql://')
if not db_url:
    print("❌ DATABASE_URL не найден!")
    sys.exit(1)

# Railway меняет postgres:// на postgresql://
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

conn = psycopg2.connect(db_url, connect_timeout=15)
cur = conn.cursor()
cur.execute('''
    INSERT INTO oauth_tokens (service_name, token_json, updated_at)
    VALUES (%s, %s, %s)
    ON CONFLICT (service_name) DO UPDATE
    SET token_json = EXCLUDED.token_json, updated_at = EXCLUDED.updated_at
''', ('google_sheets', json.dumps(new_data), datetime.utcnow()))
conn.commit()
cur.close()
conn.close()
print('✅ Токен сохранён в БД! Бот перечитает при следующем запросе.')

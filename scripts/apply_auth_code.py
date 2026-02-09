#!/usr/bin/env python3
"""
Скрипт для применения кода авторизации OAuth
"""
import sys
import os
import json
import base64
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import Flow
from loguru import logger

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_oauth_client_config():
    """Получить конфигурацию OAuth клиента из env или файла."""
    client_b64 = os.getenv("GOOGLE_OAUTH_CLIENT_JSON_B64")
    if client_b64:
        try:
            return json.loads(base64.b64decode(client_b64))
        except Exception as e:
            logger.error(f"Failed to decode GOOGLE_OAUTH_CLIENT_JSON_B64: {e}")
    
    if not os.path.exists("oauth_client.json") and os.path.exists("oauth_client.b64"):
        try:
            b64_data = Path("oauth_client.b64").read_text().strip().replace("\n", "")
            Path("oauth_client.json").write_bytes(base64.b64decode(b64_data))
        except Exception as e:
            logger.error(f"Failed to restore oauth_client.json from b64: {e}")

    if os.path.exists("oauth_client.json"):
        with open("oauth_client.json", "r") as f:
            return json.load(f)
            
    return None

def main():
    auth_code = "4/1ASc3gC1TlmhOFfxGaPrc02ZOc0hVh0GbxACP1XoxqxwhvXdcD_o3LGB5s38"
    
    print("🔑 Обрабатываю код авторизации...")
    
    client_config = get_oauth_client_config()
    
    if not client_config:
        print("❌ oauth_client.json не найден!")
        sys.exit(1)
    
    try:
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        
        print("⏳ Обмениваю код на токен...")
        flow.fetch_token(code=auth_code)
        creds = flow.credentials
        
        # Сохраняем token.json
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("✅ token.json сохранен")
        
        # Сохраняем token.b64
        b64_str = base64.b64encode(creds.to_json().encode('utf-8')).decode('utf-8')
        with open('token.b64', 'w') as token_b64:
            token_b64.write(b64_str)
        
        print("✅ token.b64 сохранен")
        
        print("\n" + "=" * 80)
        print("🎉 ТОКЕН УСПЕШНО ОБНОВЛЕН!")
        print("=" * 80)
        print("\n⚠️  ДЛЯ RAILWAY: Добавьте переменную окружения:")
        print("\nGOOGLE_OAUTH_TOKEN_JSON_B64")
        print("\nЗначение:")
        print(b64_str)
        print("\n" + "=" * 80)
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        print(f"\n❌ ОШИБКА: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

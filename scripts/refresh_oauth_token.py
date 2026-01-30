#!/usr/bin/env python3
"""
Скрипт для обновления OAuth токена Google (token.json)
Запустите этот скрипт, перейдите по ссылке, авторизуйтесь и введите код.
"""
import sys
import os
import json
import base64
from pathlib import Path

# Добавляем корневую директорию в путь
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
    
    # Попытка прочитать из b64 файла, если json нет
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
    print("🔑 OAuth Token Refresh Script")
    print("=" * 50)
    
    # Загружаем конфигурацию OAuth клиента
    client_config = get_oauth_client_config()
    
    if not client_config:
        print("❌ Ошибка: oauth_client.json не найден!")
        print("Убедитесь, что файл oauth_client.json или oauth_client.b64 существует в корне проекта.")
        sys.exit(1)
    
    print("✅ OAuth client config загружен")
    
    try:
        # Создаем Flow для авторизации
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Manual copy/paste mode
        )
        
        # Генерируем URL для авторизации
        # access_type='offline' нужен для получения refresh_token
        # prompt='consent' заставляет Google показать экран подтверждения
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        print("\n" + "=" * 50)
        print("📋 ИНСТРУКЦИЯ:")
        print("=" * 50)
        print("1. Откройте ссылку ниже в браузере")
        print("2. Авторизуйтесь в нужном Google аккаунте")
        print("3. Скопируйте код, который покажет Google")
        print("4. Вставьте код в этот терминал и нажмите Enter")
        print("=" * 50)
        print(f"\n🔗 ССЫЛКА ДЛЯ АВТОРИЗАЦИИ:\n{auth_url}\n")
        print("=" * 50)
        
        # Ждем ввода кода от пользователя
        code = input("\n🔐 Введите код авторизации: ").strip()
        
        if not code:
            print("❌ Код не введен. Выход.")
            sys.exit(1)
        
        print("\n⏳ Обмениваю код на токен...")
        
        # Обмениваем код на токены
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Сохраняем token.json
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("✅ token.json сохранен")
        
        # Также сохраняем как token.b64 для бэкапа
        b64_str = base64.b64encode(creds.to_json().encode('utf-8')).decode('utf-8')
        with open('token.b64', 'w') as token_b64:
            token_b64.write(b64_str)
        
        print("✅ token.b64 сохранен")
        
        print("\n" + "=" * 50)
        print("🎉 АВТОРИЗАЦИЯ УСПЕШНА!")
        print("=" * 50)
        print("\n⚠️  ВАЖНО: Для сохранения токена на сервере (Railway):")
        print("Добавьте эту переменную окружения:")
        print("\nGOOGLE_OAUTH_TOKEN_JSON_B64=")
        print(b64_str)
        print("\n" + "=" * 50)
        
    except Exception as e:
        logger.error(f"Ошибка при авторизации: {e}")
        print(f"\n❌ ОШИБКА: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

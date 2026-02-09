#!/usr/bin/env python3
"""
Скрипт для обновления токена через refresh_token
"""
import sys
import os
import json
import base64
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from loguru import logger

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def main():
    print("🔄 Попытка обновить токен через refresh_token...")
    
    if not Path('token.json').exists():
        print("❌ token.json не найден!")
        sys.exit(1)
    
    try:
        # Загружаем credentials
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        print(f"✓ Token loaded")
        print(f"  Valid: {creds.valid}")
        print(f"  Expired: {creds.expired}")
        print(f"  Has refresh token: {bool(creds.refresh_token)}")
        
        if creds.expired and creds.refresh_token:
            print("\n⏳ Обновляю токен...")
            creds.refresh(Request())
            
            # Сохраняем обновленный токен
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
            
            print("✅ token.json обновлен")
            
            # Сохраняем в base64
            b64_str = base64.b64encode(creds.to_json().encode('utf-8')).decode('utf-8')
            with open('token.b64', 'w') as token_b64:
                token_b64.write(b64_str)
            
            print("✅ token.b64 обновлен")
            
            print("\n" + "=" * 80)
            print("🎉 ТОКЕН УСПЕШНО ОБНОВЛЕН!")
            print("=" * 80)
            print("\n⚠️  ДЛЯ RAILWAY: Обновите переменную окружения:")
            print("\nGOOGLE_OAUTH_TOKEN_JSON_B64")
            print("\nНовое значение:")
            print(b64_str)
            print("\n" + "=" * 80)
        else:
            print("⚠️  Токен не истек или нет refresh_token")
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении токена: {e}")
        print(f"\n❌ ОШИБКА: {e}")
        print("\n⚠️  Нужна повторная авторизация!")
        print("Запустите: python scripts/refresh_oauth_token.py")
        sys.exit(1)

if __name__ == "__main__":
    main()

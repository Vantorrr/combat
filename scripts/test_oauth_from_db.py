#!/usr/bin/env python3
"""
Тестирование загрузки OAuth токена из БД
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from models.database import init_db
from config import settings


async def test_oauth():
    """Тестируем загрузку OAuth из БД"""
    
    print("🧪 Тестирование OAuth с базой данных...")
    print("=" * 60)
    
    # Инициализируем БД
    try:
        await init_db(settings.database_url_effective)
        print("✅ База данных подключена")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False
    
    # Тестируем загрузку токена
    print("\n1. Проверяем, что токен есть в БД...")
    from models.database import AsyncSessionLocal, OAuthToken
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OAuthToken).where(OAuthToken.service_name == "google_sheets")
        )
        token_row = result.scalar_one_or_none()
        
        if not token_row:
            print("❌ Токен не найден в БД. Запустите: python scripts/migrate_token_to_db.py")
            return False
        
        print(f"✅ Токен найден в БД (обновлен: {token_row.updated_at})")
    
    # Тестируем загрузку через GoogleOAuthClient
    print("\n2. Тестируем загрузку токена через GoogleOAuthClient...")
    from services.google_sheets_oauth import oauth_client
    
    oauth_client._load_credentials()
    
    if oauth_client.creds and oauth_client.creds.valid:
        print("✅ Токен загружен и валиден!")
        print(f"   - Access token: {oauth_client.creds.token[:50]}...")
        print(f"   - Refresh token есть: {bool(oauth_client.creds.refresh_token)}")
        print(f"   - Срок действия: {oauth_client.creds.expiry}")
    else:
        print("❌ Токен не загружен или невалиден")
        return False
    
    # Тестируем получение сервиса Google Sheets
    print("\n3. Тестируем подключение к Google Sheets API...")
    try:
        sheets_service = oauth_client.get_sheets_service()
        if sheets_service:
            print("✅ Google Sheets API доступен!")
            
            # Пробуем сделать простой запрос (проверка работоспособности)
            # Используем supervisor_sheet_id если есть
            if settings.supervisor_sheet_id:
                try:
                    meta = sheets_service.spreadsheets().get(
                        spreadsheetId=settings.supervisor_sheet_id
                    ).execute()
                    sheet_title = meta.get('properties', {}).get('title', 'Unknown')
                    print(f"✅ Успешно подключились к таблице: {sheet_title}")
                except Exception as e:
                    print(f"⚠️  Не удалось прочитать таблицу: {e}")
        else:
            print("❌ Не удалось получить сервис Google Sheets")
            return False
    except Exception as e:
        print(f"❌ Ошибка при получении сервиса: {e}")
        logger.exception(e)
        return False
    
    print("\n" + "=" * 60)
    print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
    print("=" * 60)
    print()
    print("Токен успешно загружается из БД и работает.")
    print("При истечении срока действия токен будет автоматически обновлен.")
    return True


def main():
    result = asyncio.run(test_oauth())
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()

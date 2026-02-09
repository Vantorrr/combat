#!/usr/bin/env python3
"""
Скрипт миграции токена из файла/env в базу данных
Запустите один раз после обновления кода
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from loguru import logger
from models.database import init_db, OAuthToken
from sqlalchemy import select
from datetime import datetime
from config import settings


async def migrate_token():
    """Мигрировать токен из файла в базу данных"""
    
    print("🔄 Миграция OAuth токена в базу данных...")
    print("=" * 60)
    
    # Инициализируем БД
    try:
        await init_db(settings.database_url_effective)
        print("✅ Подключение к базе данных установлено")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False
    
    # Импортируем AsyncSessionLocal ПОСЛЕ инициализации
    from models.database import AsyncSessionLocal
    
    # Ищем токен (приоритет: файл -> env)
    token_json_str = None
    source = None
    
    # 1. Пробуем загрузить из token.json
    if Path('token.json').exists():
        try:
            token_json_str = Path('token.json').read_text().strip()
            source = "token.json"
            print(f"✅ Токен найден в {source}")
        except Exception as e:
            print(f"⚠️  Ошибка чтения token.json: {e}")
    
    # 2. Если нет файла, пробуем env
    if not token_json_str:
        import base64
        token_b64 = os.getenv("GOOGLE_OAUTH_TOKEN_JSON_B64")
        if token_b64:
            try:
                token_json_str = base64.b64decode(token_b64).decode('utf-8')
                source = "переменной окружения GOOGLE_OAUTH_TOKEN_JSON_B64"
                print(f"✅ Токен найден в {source}")
            except Exception as e:
                print(f"⚠️  Ошибка декодирования токена из env: {e}")
    
    if not token_json_str:
        print("❌ Токен не найден ни в файле, ни в переменных окружения")
        print("   Запустите команду /auth в боте для авторизации")
        return False
    
    # Сохраняем в БД
    try:
        if not AsyncSessionLocal:
            print("❌ Ошибка: AsyncSessionLocal не инициализирован")
            return False
            
        async with AsyncSessionLocal() as session:
            # Проверяем есть ли уже токен в БД
            result = await session.execute(
                select(OAuthToken).where(OAuthToken.service_name == "google_sheets")
            )
            token_row = result.scalar_one_or_none()
            
            if token_row:
                print(f"⚠️  Токен уже существует в БД (обновлен {token_row.updated_at})")
                print("   Обновляю токен...")
                token_row.token_json = token_json_str
                token_row.updated_at = datetime.utcnow()
                action = "обновлен"
            else:
                print("📝 Создаю новую запись в БД...")
                token_row = OAuthToken(
                    service_name="google_sheets",
                    token_json=token_json_str
                )
                session.add(token_row)
                action = "сохранен"
            
            await session.commit()
            print(f"✅ Токен успешно {action} в базе данных!")
            print()
            print("=" * 60)
            print("🎉 МИГРАЦИЯ ЗАВЕРШЕНА!")
            print("=" * 60)
            print()
            print("Теперь токен будет автоматически обновляться.")
            print("Больше не нужно вручную обновлять его в Railway.")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка при сохранении в БД: {e}")
        logger.exception(e)
        return False


def main():
    result = asyncio.run(migrate_token())
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()

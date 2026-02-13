import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from models.database import init_db
import models.database as db
from config import settings
from loguru import logger

async def migrate_schema():
    """
    Добавляет новые колонки в таблицу managers, если их нет.
    Безопасно для продакшена (не удаляет данные).
    """
    print(f"🔄 Начинаю миграцию схемы БД ({settings.database_url_effective})...")
    
    await init_db(settings.database_url_effective)
    
    if not db.AsyncSessionLocal:
        print("❌ Ошибка: SessionLocal не инициализирован")
        return

    async with db.AsyncSessionLocal() as session:
        # Проверяем, есть ли колонка login
        try:
            # Попытка выбрать login. Если упадет - значит колонки нет
            await session.execute(text("SELECT login FROM managers LIMIT 1"))
            print("✅ Колонки уже существуют.")
        except Exception:
            print("🛠 Колонки не найдены. Добавляю...")
            try:
                # Для SQLite и PostgreSQL синтаксис может отличаться
                # SQLite не поддерживает ADD COLUMN ... UNIQUE в одной команде
                
                # 1. login (без UNIQUE пока)
                await session.execute(text("ALTER TABLE managers ADD COLUMN login VARCHAR(255)"))
                
                # 2. password_hash
                await session.execute(text("ALTER TABLE managers ADD COLUMN password_hash VARCHAR(255)"))
                
                # 3. role
                await session.execute(text("ALTER TABLE managers ADD COLUMN role VARCHAR(50) DEFAULT 'manager'"))
                
                # 4. Создаем уникальный индекс для login (работает везде)
                try:
                    await session.execute(text("CREATE UNIQUE INDEX idx_managers_login ON managers (login)"))
                except Exception as e:
                    print(f"⚠️ Не удалось создать индекс (возможно уже есть): {e}")

                await session.commit()
                print("✅ Колонки успешно добавлены!")
            except Exception as e:
                print(f"❌ Ошибка при добавлении колонок: {e}")
                # Возможно база на SQLite и там ALTER TABLE ограничен, но для Postgres (Railway) это сработает
                
if __name__ == "__main__":
    asyncio.run(migrate_schema())

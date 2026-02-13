import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from models.database import init_db, Manager
import models.database as db
from backend.security import get_password_hash
from config import settings

async def create_admin_user():
    """Создать первого админа для веб-доступа"""
    print("👤 Создание администратора...")
    
    await init_db(settings.database_url_effective)
    
    username = input("Введите логин: ").strip()
    password = input("Введите пароль: ").strip()
    
    if not username or not password:
        print("❌ Логин и пароль обязательны")
        return

    if not db.AsyncSessionLocal:
        print("❌ Ошибка: SessionLocal не инициализирован")
        return

    async with db.AsyncSessionLocal() as session:
        # Проверяем, есть ли уже такой пользователь
        result = await session.execute(select(Manager).where(Manager.login == username))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            print(f"⚠️ Пользователь {username} уже существует. Обновляю пароль...")
            existing_user.password_hash = get_password_hash(password)
            existing_user.role = "admin"
        else:
            # Создаем нового (или привязываем к существующему менеджеру без логина?)
            # Для простоты создадим нового, но в идеале нужно искать по telegram_id или имени
            print("📝 Создаю нового пользователя...")
            new_user = Manager(
                full_name="Admin",
                login=username,
                password_hash=get_password_hash(password),
                role="admin",
                is_active=True
            )
            session.add(new_user)
            
        await session.commit()
        print("✅ Администратор успешно создан/обновлен!")

if __name__ == "__main__":
    asyncio.run(create_admin_user())

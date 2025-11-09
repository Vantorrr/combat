"""
Скрипт миграции данных из локальной SQLite в Railway Postgres.

Использование:
1. Убедись что локально есть crmbot.db с данными
2. Получи DATABASE_URL от Railway Postgres (из Variables)
3. Запусти: python scripts/migrate_sqlite_to_postgres.py
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from models.database import Base, Manager, CallSession
from loguru import logger


async def export_from_sqlite(sqlite_path: str = "crmbot.db"):
    """Экспортировать данные из SQLite"""
    if not os.path.exists(sqlite_path):
        logger.error(f"SQLite database not found: {sqlite_path}")
        return None, None
    
    logger.info(f"Reading data from {sqlite_path}...")
    
    # Подключаемся к SQLite синхронно (проще для чтения)
    engine = create_engine(f"sqlite:///{sqlite_path}")
    
    managers = []
    call_sessions = []
    
    with engine.connect() as conn:
        # Читаем менеджеров
        result = conn.execute(text("SELECT * FROM managers"))
        for row in result:
            # Парсим created_at если это строка
            created_at = row.created_at
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            
            managers.append({
                'id': row.id,
                'telegram_id': row.telegram_id,
                'full_name': row.full_name,
                'google_sheet_id': row.google_sheet_id,
                'is_active': row.is_active,
                'created_at': created_at
            })
        
        # Читаем сессии звонков
        result = conn.execute(text("SELECT * FROM call_sessions"))
        for row in result:
            # Парсим даты если это строки
            next_call_date = row.next_call_date
            if isinstance(next_call_date, str):
                next_call_date = datetime.fromisoformat(next_call_date)
            
            created_at = row.created_at
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            
            call_sessions.append({
                'id': row.id,
                'manager_id': row.manager_id,
                'session_type': row.session_type,
                'company_inn': row.company_inn,
                'company_name': row.company_name,
                'contact_name': row.contact_name,
                'contact_phone': row.contact_phone,
                'comment': row.comment,
                'next_call_date': next_call_date,
                'created_at': created_at
            })
    
    logger.info(f"Exported {len(managers)} managers and {len(call_sessions)} call sessions")
    return managers, call_sessions


async def import_to_postgres(postgres_url: str, managers_data: list, sessions_data: list):
    """Импортировать данные в PostgreSQL"""
    logger.info(f"Connecting to PostgreSQL...")
    
    # Создаём async engine для Postgres
    engine = create_async_engine(postgres_url, echo=False)
    
    # Пересоздаём таблицы (удаляем старые и создаём новые с правильной схемой)
    async with engine.begin() as conn:
        logger.info("Dropping existing tables...")
        await conn.run_sync(Base.metadata.drop_all)
        logger.info("Creating tables with new schema...")
        await conn.run_sync(Base.metadata.create_all)
    
    # Создаём сессию
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    
    async with AsyncSessionLocal() as session:
        # Импортируем менеджеров
        logger.info(f"Importing {len(managers_data)} managers...")
        for m_data in managers_data:
            # Проверяем, не существует ли уже менеджер с таким telegram_id
            result = await session.execute(
                text("SELECT id FROM managers WHERE telegram_id = :tid"),
                {"tid": m_data['telegram_id']}
            )
            existing = result.fetchone()
            
            if existing:
                logger.info(f"Manager {m_data['full_name']} already exists, skipping")
                continue
            
            manager = Manager(
                telegram_id=m_data['telegram_id'],
                full_name=m_data['full_name'],
                google_sheet_id=m_data['google_sheet_id'],
                is_active=m_data['is_active'],
                created_at=m_data['created_at']
            )
            session.add(manager)
        
        await session.commit()
        logger.info("Managers imported successfully")
        
        # Импортируем сессии звонков
        logger.info(f"Importing {len(sessions_data)} call sessions...")
        for s_data in sessions_data:
            call_session = CallSession(
                manager_id=s_data['manager_id'],
                session_type=s_data['session_type'],
                company_inn=s_data['company_inn'],
                company_name=s_data['company_name'],
                contact_name=s_data['contact_name'],
                contact_phone=s_data['contact_phone'],
                comment=s_data['comment'],
                next_call_date=s_data['next_call_date'],
                created_at=s_data['created_at']
            )
            session.add(call_session)
        
        await session.commit()
        logger.info("Call sessions imported successfully")
    
    await engine.dispose()


async def main():
    """Основная функция миграции"""
    logger.info("=== SQLite to PostgreSQL Migration ===")
    
    # 1. Экспортируем из SQLite
    managers, sessions = await export_from_sqlite("crmbot.db")
    
    if managers is None:
        logger.error("Failed to export data from SQLite")
        return
    
    if not managers:
        logger.warning("No data to migrate")
        return
    
    # 2. Получаем PostgreSQL URL
    postgres_url = os.getenv("RAILWAY_POSTGRES_URL")
    
    if not postgres_url:
        logger.error(
            "RAILWAY_POSTGRES_URL not found in environment.\n"
            "Please set it before running migration:\n"
            "export RAILWAY_POSTGRES_URL='postgresql+asyncpg://user:pass@host:port/db?sslmode=require'"
        )
        return
    
    # Нормализуем URL (на случай если передан без asyncpg)
    if postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # asyncpg использует ssl=require, а не sslmode=require
    if "ssl=" not in postgres_url and "sslmode=" not in postgres_url:
        # Для Railway internal адреса SSL не нужен
        if "railway.internal" not in postgres_url:
            separator = "&" if "?" in postgres_url else "?"
            postgres_url = f"{postgres_url}{separator}ssl=require"
    
    # 3. Импортируем в PostgreSQL
    await import_to_postgres(postgres_url, managers, sessions)
    
    logger.info("=== Migration completed successfully ===")


if __name__ == "__main__":
    asyncio.run(main())


from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from datetime import datetime

Base = declarative_base()


class Manager(Base):
    __tablename__ = "managers"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    google_sheet_id = Column(String, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с сессиями
    sessions = relationship("CallSession", back_populates="manager")


class CallSession(Base):
    __tablename__ = "call_sessions"
    
    id = Column(Integer, primary_key=True)
    manager_id = Column(Integer, ForeignKey("managers.id"))
    session_type = Column(String)  # "new" или "repeat"
    company_inn = Column(String)
    company_name = Column(String)
    contact_name = Column(String)
    contact_phone = Column(String)
    comment = Column(String)
    next_call_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с менеджером
    manager = relationship("Manager", back_populates="sessions")


# Настройка асинхронной базы данных
async_engine = None
AsyncSessionLocal = None


async def init_db(database_url: str):
    global async_engine, AsyncSessionLocal
    
    # URL уже содержит правильный драйвер, не нужно менять
    async_engine = create_async_engine(database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)
    
    # Создаем таблицы
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

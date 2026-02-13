from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from datetime import datetime
import ssl as _ssl
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

Base = declarative_base()


class OAuthToken(Base):
    """Хранилище OAuth токена Google для автоматического обновления"""
    __tablename__ = "oauth_tokens"
    
    id = Column(Integer, primary_key=True)
    service_name = Column(String, unique=True, nullable=False, default="google_sheets")
    token_json = Column(Text, nullable=False)  # JSON с access_token, refresh_token и т.д.
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class Manager(Base):
    __tablename__ = "managers"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=True) # Теперь может быть пустым (если только веб-доступ)
    full_name = Column(String, nullable=False)
    google_sheet_id = Column(String, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Новые поля для Web-доступа
    login = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=True)
    role = Column(String, default="manager") # "admin" или "manager"
    
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
    
    connect_args = {}
    
    # asyncpg не поддерживает ssl=require как параметр URL — нужно передавать через connect_args
    if "postgresql+asyncpg://" in database_url and ("ssl=require" in database_url or "sslmode=require" in database_url):
        # Убираем ssl/sslmode из URL
        parsed = urlparse(database_url)
        qs = parse_qs(parsed.query)
        qs.pop("ssl", None)
        qs.pop("sslmode", None)
        new_query = urlencode(qs, doseq=True)
        database_url = urlunparse(parsed._replace(query=new_query))
        
        # Передаём SSL через connect_args
        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx
    
    async_engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
    AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)
    
    # Создаем таблицы
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

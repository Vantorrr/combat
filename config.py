from pydantic_settings import BaseSettings
from typing import List, Union
import os
import re


class Settings(BaseSettings):
    # Telegram Bot
    bot_token: str
    
    # Google Sheets
    google_sheets_credentials_file: str = "credentials.json"
    manager_sheet_template_id: str
    supervisor_sheet_id: str
    
    # DataNewton API
    datanewton_api_key: str
    datanewton_base_url: str = "https://api.datanewton.ru/v1"
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./crmbot.db"
    
    # Admin Telegram IDs
    admin_ids: Union[str, List[int]] = []
    
    # Scheduler
    reminder_time: str = "09:00"  # fallback
    reminder_times: str = "10:00,15:00,17:00"  # comma separated HH:MM
    timezone: str = "Europe/Moscow"
    
    class Config:
        env_file = ".env"
        
    @property
    def admin_ids_list(self) -> List[int]:
        if isinstance(self.admin_ids, str):
            return [int(id.strip()) for id in self.admin_ids.split(",") if id.strip()]
        return self.admin_ids

    @property
    def reminder_times_list(self) -> List[str]:
        raw = (self.reminder_times or "").strip()
        if not raw:
            return [self.reminder_time]
        return [t.strip() for t in raw.split(",") if t.strip()]
    
    @property
    def database_url_effective(self) -> str:
        """
        Возвращает нормализованный DATABASE_URL:
        - подставляет PG* переменные Railway, если в строке есть плейсхолдеры ${...}
        - заменяет postgresql:// на postgresql+asyncpg://
        - добавляет sslmode=require для Railway, если это PostgreSQL и параметр отсутствует
        """
        db_url = os.getenv("DATABASE_URL", self.database_url)
        
        # Если переданы плейсхолдеры вида ${PG...} — собираем вручную из окружения
        if "${" in db_url:
            # Railway Postgres плагин создаёт переменные с префиксом, попробуем все варианты
            pg_user = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
            pg_password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
            pg_host = os.getenv("PGHOST") or os.getenv("POSTGRES_HOST")
            pg_port = os.getenv("PGPORT") or os.getenv("POSTGRES_PORT", "5432")
            pg_db = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")
            
            if all([pg_user, pg_password, pg_host, pg_port, pg_db]):
                db_url = f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
            else:
                # Если не удалось собрать — попробуем взять DATABASE_URL напрямую из плагина
                # Railway обычно создаёт DATABASE_URL автоматически
                raw_db_url = os.getenv("DATABASE_URL")
                if raw_db_url and not "${" in raw_db_url:
                    db_url = raw_db_url
        
        # Нормализуем схему
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        # Добавим sslmode=require если это PostgreSQL и параметра нет
        if db_url.startswith("postgresql+asyncpg://") and "sslmode=" not in db_url:
            separator = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{separator}sslmode=require"
        
        return db_url


settings = Settings()

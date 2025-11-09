from pydantic_settings import BaseSettings
from typing import List, Union
import os


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


settings = Settings()

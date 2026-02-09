from __future__ import annotations

from typing import Optional
import os
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from loguru import logger

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Глобальный executor для БД операций
_db_executor = ThreadPoolExecutor(max_workers=2)


class GoogleOAuthClient:
    def __init__(self, oauth_client_file: str = "oauth_client.json", token_file: str = "token.json") -> None:
        self.oauth_client_file = oauth_client_file
        self.token_file = token_file
        self.creds: Optional[Credentials] = None

    def _load_token_from_db(self) -> Optional[str]:
        """Загрузить токен из БД (синхронная обертка)"""
        try:
            # Запускаем async код в отдельном thread чтобы избежать проблем с event loop
            def run_async_in_thread():
                return asyncio.run(self._async_load_token_from_db())
            
            future = _db_executor.submit(run_async_in_thread)
            return future.result(timeout=5)  # Ждем максимум 5 секунд
        except Exception as e:
            logger.debug(f"Could not load token from DB: {e}")
            return None
    
    async def _async_load_token_from_db(self) -> Optional[str]:
        """Асинхронная загрузка токена из БД"""
        try:
            from models.database import AsyncSessionLocal, OAuthToken
            from sqlalchemy import select
            
            if not AsyncSessionLocal:
                return None
                
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(OAuthToken).where(OAuthToken.service_name == "google_sheets")
                )
                token_row = result.scalar_one_or_none()
                if token_row:
                    logger.info("Loaded OAuth token from database")
                    return token_row.token_json
        except Exception as e:
            logger.debug(f"Error loading token from DB: {e}")
        return None
    
    def _save_token_to_db(self, token_json: str) -> bool:
        """Сохранить токен в БД (синхронная обертка)"""
        try:
            # Запускаем async код в отдельном thread
            def run_async_in_thread():
                return asyncio.run(self._async_save_token_to_db(token_json))
            
            # Не ждем результата - сохранение в фоне
            _db_executor.submit(run_async_in_thread)
            logger.debug("Scheduled token save to DB in background")
            return True
        except Exception as e:
            logger.error(f"Could not save token to DB: {e}")
            return False
    
    async def _async_save_token_to_db(self, token_json: str) -> bool:
        """Асинхронное сохранение токена в БД"""
        try:
            from models.database import AsyncSessionLocal, OAuthToken
            from sqlalchemy import select
            from datetime import datetime
            
            if not AsyncSessionLocal:
                return False
                
            async with AsyncSessionLocal() as session:
                # Проверяем есть ли уже запись
                result = await session.execute(
                    select(OAuthToken).where(OAuthToken.service_name == "google_sheets")
                )
                token_row = result.scalar_one_or_none()
                
                if token_row:
                    # Обновляем существующую запись
                    token_row.token_json = token_json
                    token_row.updated_at = datetime.utcnow()
                else:
                    # Создаем новую запись
                    token_row = OAuthToken(
                        service_name="google_sheets",
                        token_json=token_json
                    )
                    session.add(token_row)
                
                await session.commit()
                logger.info("Saved OAuth token to database")
                return True
        except Exception as e:
            logger.error(f"Error saving token to DB: {e}")
            return False

    def _load_credentials(self) -> None:
        """Загрузка и обновление токена.
        Приоритет: БД -> файл token.json -> env переменная
        На сервере НЕ запускаем run_local_server, ожидаем, что токен уже создан через /auth.
        """
        # 1. Пытаемся загрузить из БД
        token_json_from_db = self._load_token_from_db()
        if token_json_from_db:
            try:
                token_data = json.loads(token_json_from_db)
                self.creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                logger.info("Using OAuth token from database")
            except Exception as e:
                logger.error(f"Error parsing token from DB: {e}")
                self.creds = None
        
        # 2. Если нет в БД, пытаемся загрузить из файла
        if not self.creds and os.path.exists(self.token_file):
            try:
                self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
                logger.info("Using OAuth token from file")
                # Сохраняем в БД для будущих использований
                self._save_token_to_db(self.creds.to_json())
            except Exception as e:
                logger.error(f"Error loading token.json: {e}")
                self.creds = None

        # 3. Проверяем валидность и обновляем если нужно
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    logger.info("Refreshing expired OAuth token...")
                    self.creds.refresh(Request())
                    
                    # Сохраняем обновленный токен в БД
                    updated_token_json = self.creds.to_json()
                    self._save_token_to_db(updated_token_json)
                    
                    # Также сохраняем в файл для совместимости
                    with open(self.token_file, "w") as token:
                        token.write(updated_token_json)
                    
                    logger.info("✅ OAuth token refreshed and saved to database")
                except Exception as e:
                    logger.error(f"Failed to refresh token: {e}")
                    self.creds = None
            
            # Если после рефреша всё ещё нет кредов — не запускаем локальный сервер
            # (мы на сервере, браузера нет). Пусть пользователь юзает /auth.
            if not self.creds or not self.creds.valid:
                logger.warning("OAuth token invalid/missing and cannot be refreshed. Please use /auth command.")
                return

    def get_sheets_service(self):
        try:
            self._load_credentials()
            if self.creds and self.creds.valid:
                return build("sheets", "v4", credentials=self.creds)
        except Exception as e:
            logger.error(f"Failed to get sheets service via OAuth: {e}")
        return None

    def get_drive_service(self):
        self._load_credentials()
        return build("drive", "v3", credentials=self.creds)


oauth_client = GoogleOAuthClient()






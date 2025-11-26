from __future__ import annotations

from typing import Optional
import os
import json
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


class GoogleOAuthClient:
    def __init__(self, oauth_client_file: str = "oauth_client.json", token_file: str = "token.json") -> None:
        self.oauth_client_file = oauth_client_file
        self.token_file = token_file
        self.creds: Optional[Credentials] = None

    def _load_credentials(self) -> None:
        """Загрузка и обновление токена.
        На сервере НЕ запускаем run_local_server, ожидаем, что токен уже создан через /auth.
        """
        if os.path.exists(self.token_file):
            try:
                self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
            except Exception as e:
                logger.error(f"Error loading token.json: {e}")
                self.creds = None

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    logger.info("Refreshing expired OAuth token...")
                    self.creds.refresh(Request())
                    # Сохраняем обновленный токен
                    with open(self.token_file, "w") as token:
                        token.write(self.creds.to_json())
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






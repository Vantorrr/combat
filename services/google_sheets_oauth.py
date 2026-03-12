from __future__ import annotations

from typing import Optional
import os
import json
from datetime import datetime
from loguru import logger

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_db_url() -> Optional[str]:
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url or None


def _save_token_sync(token_json: str) -> bool:
    """Синхронное сохранение токена в БД через psycopg2 — надёжно при рестарте."""
    db_url = _get_db_url()
    if not db_url:
        logger.warning("DATABASE_URL not set, cannot save token to DB")
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=10)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oauth_tokens (service_name, token_json, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (service_name) DO UPDATE
            SET token_json = EXCLUDED.token_json, updated_at = EXCLUDED.updated_at
            """,
            ("google_sheets", token_json, datetime.utcnow()),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ OAuth token saved to DB (sync)")
        return True
    except Exception as e:
        logger.error(f"Failed to save token to DB (sync): {e}")
        return False


def _load_token_sync() -> Optional[str]:
    """Синхронная загрузка токена из БД через psycopg2."""
    db_url = _get_db_url()
    if not db_url:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=10)
        cur = conn.cursor()
        cur.execute(
            "SELECT token_json FROM oauth_tokens WHERE service_name = %s",
            ("google_sheets",),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            logger.info("Loaded OAuth token from DB (sync)")
            return row[0]
    except Exception as e:
        logger.debug(f"Could not load token from DB (sync): {e}")
    return None


class GoogleOAuthClient:
    def __init__(self, oauth_client_file: str = "oauth_client.json", token_file: str = "token.json") -> None:
        self.oauth_client_file = oauth_client_file
        self.token_file = token_file
        self.creds: Optional[Credentials] = None

    def _load_credentials(self) -> None:
        """Загрузка и обновление токена. Приоритет: БД -> файл token.json."""

        # 1. Загружаем из БД (psycopg2, синхронно и надёжно)
        token_json = _load_token_sync()
        if token_json:
            try:
                self.creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
            except Exception as e:
                logger.error(f"Error parsing token from DB: {e}")
                self.creds = None

        # 2. Fallback — файл token.json
        if not self.creds and os.path.exists(self.token_file):
            try:
                self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
                logger.info("Using OAuth token from file")
                _save_token_sync(self.creds.to_json())
            except Exception as e:
                logger.error(f"Error loading token.json: {e}")
                self.creds = None

        # 3. Если токен истёк — обновляем через refresh_token и СРАЗУ сохраняем в БД
        if self.creds and not self.creds.valid and self.creds.expired and self.creds.refresh_token:
            try:
                logger.info("Refreshing expired OAuth token...")
                self.creds.refresh(Request())
                _save_token_sync(self.creds.to_json())
                logger.info("✅ OAuth token refreshed and saved")
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                self.creds = None

        if not self.creds or not self.creds.valid:
            logger.warning("OAuth token invalid/missing. Need to re-authorize.")

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
        if self.creds and self.creds.valid:
            return build("drive", "v3", credentials=self.creds)
        return None


oauth_client = GoogleOAuthClient()






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
        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.oauth_client_file, SCOPES)
                self.creds = flow.run_local_server(port=0)
            with open(self.token_file, "w") as token:
                token.write(self.creds.to_json())

    def get_sheets_service(self):
        self._load_credentials()
        return build("sheets", "v4", credentials=self.creds)

    def get_drive_service(self):
        self._load_credentials()
        return build("drive", "v3", credentials=self.creds)


oauth_client = GoogleOAuthClient()






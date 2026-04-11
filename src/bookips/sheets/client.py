"""Google Sheets / Drive API 클라이언트 (OAuth2 인증)

PKCE 없이 직접 OAuth2 플로우 구현 (Cloud Run 호환).
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from pathlib import Path
from typing import Optional

import gspread
import requests as http_requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from bookips.config import ROOT_DIR, get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TOKEN_PATH = ROOT_DIR / "data" / "token.json"

AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleClient:
    """Google Sheets + Drive 통합 클라이언트"""

    def __init__(self) -> None:
        self._creds: Optional[Credentials] = None
        self._gc: Optional[gspread.Client] = None
        self._drive = None

    @property
    def is_authenticated(self) -> bool:
        return self._creds is not None and self._creds.valid

    def load_token(self) -> bool:
        if not TOKEN_PATH.exists():
            return False
        try:
            self._creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as e:
            logger.warning("토큰 로드 실패: %s", e)
            return False

        if self._creds and self._creds.expired and self._creds.refresh_token:
            try:
                self._creds.refresh(Request())
                self._save_token()
            except Exception as e:
                logger.warning("토큰 갱신 실패: %s", e)
                return False

        if self._creds and self._creds.valid:
            self._init_clients()
            return True
        return False

    def get_auth_url(self) -> str:
        """OAuth2 인증 URL 생성 (PKCE 없이)"""
        settings = get_settings()
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "scope": " ".join(SCOPES),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> None:
        """인증 코드 → 토큰 교환 (PKCE 없이 직접 HTTP 요청)"""
        settings = get_settings()
        resp = http_requests.post(TOKEN_URL, data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })

        if resp.status_code != 200:
            raise RuntimeError(f"토큰 교환 실패: {resp.status_code} {resp.text}")

        token_data = resp.json()
        if "error" in token_data:
            raise RuntimeError(f"토큰 오류: {token_data['error']} - {token_data.get('error_description', '')}")

        self._creds = Credentials(
            token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=TOKEN_URL,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=SCOPES,
        )
        self._save_token()
        self._init_clients()
        logger.info("Google 인증 완료, 토큰 저장됨")

    def _save_token(self) -> None:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(self._creds.to_json())

    def _init_clients(self) -> None:
        self._gc = gspread.authorize(self._creds)
        self._drive = build("drive", "v3", credentials=self._creds)

    # ─── Spreadsheet 접근 ────────────────────────────────────────

    def open_spreadsheet(self, spreadsheet_id: str) -> gspread.Spreadsheet:
        self._require_auth()
        return self._gc.open_by_key(spreadsheet_id)

    def get_worksheet(self, spreadsheet_id: str, title: str) -> gspread.Worksheet:
        ss = self.open_spreadsheet(spreadsheet_id)
        return ss.worksheet(title)

    def get_all_values(self, spreadsheet_id: str, worksheet_title: str) -> list[list[str]]:
        ws = self.get_worksheet(spreadsheet_id, worksheet_title)
        return ws.get_all_values()

    # ─── Drive 파일 조작 ─────────────────────────────────────────

    def copy_file(self, file_id: str, new_name: str) -> str:
        self._require_auth()
        result = self._drive.files().copy(
            fileId=file_id,
            body={"name": new_name},
        ).execute()
        new_id = result["id"]
        logger.info("파일 복사: %s → %s (%s)", file_id, new_name, new_id)
        return new_id

    def get_file_id_from_url(self, url: str) -> Optional[str]:
        import re
        patterns = [
            r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
            r"/file/d/([a-zA-Z0-9_-]+)",
            r"id=([a-zA-Z0-9_-]+)",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    def get_spreadsheet_url(self, file_id: str) -> str:
        return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"

    def _require_auth(self) -> None:
        if not self.is_authenticated:
            raise RuntimeError("Google 인증이 필요합니다. /auth/login에서 인증해 주세요.")


_client: Optional[GoogleClient] = None


def get_google_client() -> GoogleClient:
    global _client
    if _client is None:
        _client = GoogleClient()
        _client.load_token()
    return _client

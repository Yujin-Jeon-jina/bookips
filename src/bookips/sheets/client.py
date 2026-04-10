"""Google Sheets / Drive API 클라이언트 (OAuth2 인증)

OAuth2 흐름:
  1. 웹 브라우저에서 Google 로그인 → 인증 코드 획득
  2. 인증 코드 → 액세스 토큰 + 리프레시 토큰 교환
  3. 토큰을 data/token.json에 저장
  4. 이후 자동 갱신
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from bookips.config import ROOT_DIR, get_settings

logger = logging.getLogger(__name__)

# Google API 스코프
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TOKEN_PATH = ROOT_DIR / "data" / "token.json"


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
        """저장된 토큰 로드 시도. True if valid."""
        if not TOKEN_PATH.exists():
            return False
        try:
            self._creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as e:
            logger.warning("토큰 파일 로드 실패: %s", e)
            return False

        if self._creds and self._creds.expired and self._creds.refresh_token:
            try:
                self._creds.refresh(Request())
                self._save_token()
                logger.info("토큰 갱신 완료")
            except Exception as e:
                logger.warning("토큰 갱신 실패: %s", e)
                return False

        if self._creds and self._creds.valid:
            self._init_clients()
            return True
        return False

    def get_auth_url(self) -> str:
        """OAuth2 인증 URL 생성 (최초 인증 시)"""
        settings = get_settings()
        flow = self._make_flow(settings)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def exchange_code(self, code: str) -> None:
        """인증 코드 → 토큰 교환 및 저장"""
        settings = get_settings()
        flow = self._make_flow(settings)
        flow.fetch_token(code=code)
        self._creds = flow.credentials
        self._save_token()
        self._init_clients()
        logger.info("Google 인증 완료, 토큰 저장됨")

    def _make_flow(self, settings) -> Flow:
        client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )

    def _save_token(self) -> None:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(self._creds.to_json())

    def _init_clients(self) -> None:
        self._gc = gspread.authorize(self._creds)
        self._drive = build("drive", "v3", credentials=self._creds)

    # ─── Spreadsheet 접근 ────────────────────────────────────────

    def open_spreadsheet(self, spreadsheet_id: str) -> gspread.Spreadsheet:
        """스프레드시트 열기"""
        self._require_auth()
        return self._gc.open_by_key(spreadsheet_id)

    def get_worksheet(self, spreadsheet_id: str, title: str) -> gspread.Worksheet:
        """특정 탭(워크시트) 가져오기"""
        ss = self.open_spreadsheet(spreadsheet_id)
        return ss.worksheet(title)

    def get_all_values(self, spreadsheet_id: str, worksheet_title: str) -> list[list[str]]:
        """워크시트 전체 값 조회"""
        ws = self.get_worksheet(spreadsheet_id, worksheet_title)
        return ws.get_all_values()

    # ─── Drive 파일 조작 ─────────────────────────────────────────

    def copy_file(self, file_id: str, new_name: str) -> str:
        """Google Drive 파일 복사 → 새 파일 ID 반환"""
        self._require_auth()
        result = self._drive.files().copy(
            fileId=file_id,
            body={"name": new_name},
        ).execute()
        new_id = result["id"]
        logger.info("파일 복사 완료: %s → %s (%s)", file_id, new_name, new_id)
        return new_id

    def get_file_id_from_url(self, url: str) -> Optional[str]:
        """Google Drive/Sheets URL에서 파일 ID 추출"""
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


# 싱글턴 클라이언트 (앱 시작 시 초기화)
_client: Optional[GoogleClient] = None


def get_google_client() -> GoogleClient:
    global _client
    if _client is None:
        _client = GoogleClient()
        _client.load_token()
    return _client

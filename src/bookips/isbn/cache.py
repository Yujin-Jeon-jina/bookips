"""ISBN 매핑 캐시 (SQLite 로컬 + Google Sheets 영구 저장)

SQLite: 앱 실행 중 빠른 조회용 로컬 캐시
Google Sheets: 재배포/재시작 시에도 유지되는 영구 저장소

앱 시작 시 Google Sheets → SQLite로 동기화.
매핑 추가/삭제 시 SQLite + Google Sheets 동시 업데이트.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from bookips.config import get_settings

logger = logging.getLogger(__name__)

MAPPING_TAB_NAME = "isbn_mappings"
MAPPING_HEADERS = ["usage_isbn", "contract_isbn", "match_method", "confidence", "created_at", "updated_at"]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS isbn_mappings (
    usage_isbn      TEXT PRIMARY KEY,
    contract_isbn   TEXT NOT NULL,
    match_method    TEXT NOT NULL,
    confidence      REAL NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS isbn_metadata_cache (
    isbn            TEXT PRIMARY KEY,
    title           TEXT,
    author          TEXT,
    publisher       TEXT,
    set_isbn        TEXT,
    edition         TEXT,
    fetched_at      TEXT NOT NULL
);
"""


class ISBNCache:
    """SQLite 기반 ISBN 매핑 캐시"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = get_settings().database_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLE)
            conn.commit()

    # ─── 매핑 캐시 ───────────────────────────────────────────────

    def get_mapping(self, usage_isbn: str) -> Optional[dict]:
        """사용 ISBN → 계약 ISBN 매핑 조회.

        Returns:
            {'contract_isbn': str, 'match_method': str, 'confidence': float} 또는 None
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT contract_isbn, match_method, confidence FROM isbn_mappings WHERE usage_isbn = ?",
                (usage_isbn,),
            ).fetchone()
        if row:
            return dict(row)
        return None

    def save_mapping(
        self,
        usage_isbn: str,
        contract_isbn: str,
        match_method: str,
        confidence: float,
    ) -> None:
        """ISBN 매핑 저장 (SQLite + Google Sheets)"""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO isbn_mappings (usage_isbn, contract_isbn, match_method, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_isbn) DO UPDATE SET
                    contract_isbn = excluded.contract_isbn,
                    match_method  = excluded.match_method,
                    confidence    = excluded.confidence,
                    updated_at    = excluded.updated_at
                """,
                (usage_isbn, contract_isbn, match_method, confidence, now, now),
            )
            conn.commit()
        logger.debug("매핑 저장: %s → %s (%s, %.2f)", usage_isbn, contract_isbn, match_method, confidence)
        self._sync_to_sheet()

    def delete_mapping(self, usage_isbn: str) -> bool:
        """매핑 삭제 (SQLite + Google Sheets)"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM isbn_mappings WHERE usage_isbn = ?", (usage_isbn,)
            )
            conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            self._sync_to_sheet()
        return deleted

    def list_mappings(self) -> list[dict]:
        """전체 매핑 목록 반환"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM isbn_mappings ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ─── 서지정보 메타데이터 캐시 ─────────────────────────────────

    def get_metadata(self, isbn: str) -> Optional[dict]:
        """서지정보 캐시 조회 (국립중앙도서관 API 결과)"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM isbn_metadata_cache WHERE isbn = ?", (isbn,)
            ).fetchone()
        return dict(row) if row else None

    def save_metadata(
        self,
        isbn: str,
        title: str,
        author: str,
        publisher: str,
        set_isbn: str = "",
        edition: str = "",
    ) -> None:
        """서지정보 캐시 저장 (upsert) - SQLite만 (메타데이터는 영구 저장 불필요)"""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO isbn_metadata_cache (isbn, title, author, publisher, set_isbn, edition, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(isbn) DO UPDATE SET
                    title = excluded.title,
                    author = excluded.author,
                    publisher = excluded.publisher,
                    set_isbn = excluded.set_isbn,
                    edition = excluded.edition,
                    fetched_at = excluded.fetched_at
                """,
                (isbn, title, author, publisher, set_isbn, edition, now),
            )
            conn.commit()

    # ─── Google Sheets 영구 저장 ──────────────────────────────────

    def sync_from_sheet(self) -> int:
        """Google Sheets → SQLite로 매핑 로드 (앱 시작 시)

        Returns:
            로드된 매핑 수
        """
        try:
            from bookips.sheets.client import get_google_client
            client = get_google_client()
            if not client.is_authenticated:
                return 0

            settings = get_settings()
            ss = client.open_spreadsheet(settings.settlement.spreadsheet_id)

            # isbn_mappings 탭 찾기
            try:
                ws = ss.worksheet(MAPPING_TAB_NAME)
            except Exception:
                logger.info("'%s' 탭 없음 — 초기 상태", MAPPING_TAB_NAME)
                return 0

            rows = ws.get_all_values()
            if len(rows) <= 1:  # 헤더만 있거나 비어있음
                return 0

            count = 0
            for row in rows[1:]:  # 헤더 건너뛰기
                if len(row) >= 6 and row[0].strip():
                    with self._connect() as conn:
                        conn.execute(
                            """
                            INSERT INTO isbn_mappings (usage_isbn, contract_isbn, match_method, confidence, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(usage_isbn) DO UPDATE SET
                                contract_isbn = excluded.contract_isbn,
                                match_method  = excluded.match_method,
                                confidence    = excluded.confidence,
                                updated_at    = excluded.updated_at
                            """,
                            (row[0], row[1], row[2], float(row[3] or 0), row[4], row[5]),
                        )
                        conn.commit()
                    count += 1

            logger.info("Google Sheets에서 매핑 %d건 로드 완료", count)
            return count
        except Exception as e:
            logger.warning("Sheets 매핑 동기화 실패: %s", e)
            return 0

    def _sync_to_sheet(self) -> None:
        """SQLite → Google Sheets로 전체 매핑 쓰기"""
        try:
            from bookips.sheets.client import get_google_client
            client = get_google_client()
            if not client.is_authenticated:
                return

            settings = get_settings()
            ss = client.open_spreadsheet(settings.settlement.spreadsheet_id)

            # isbn_mappings 탭 찾기 또는 생성
            try:
                ws = ss.worksheet(MAPPING_TAB_NAME)
            except Exception:
                ws = ss.add_worksheet(title=MAPPING_TAB_NAME, rows=1000, cols=6)
                logger.info("'%s' 탭 생성", MAPPING_TAB_NAME)

            # 전체 매핑 읽기
            mappings = self.list_mappings()

            # 시트 초기화 + 헤더 + 데이터 쓰기
            ws.clear()
            values = [MAPPING_HEADERS]
            for m in mappings:
                values.append([
                    m["usage_isbn"],
                    m["contract_isbn"],
                    m["match_method"],
                    str(m["confidence"]),
                    m["created_at"],
                    m["updated_at"],
                ])
            if values:
                ws.update(f"A1:F{len(values)}", values)

            logger.debug("Google Sheets에 매핑 %d건 동기화 완료", len(mappings))
        except Exception as e:
            logger.warning("Sheets 매핑 저장 실패: %s", e)

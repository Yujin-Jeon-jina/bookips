"""ISBN 매핑 캐시 (SQLite 기반)

한번 해결된 ISBN 매핑을 저장하여 다음 달에 재처리 불필요.
수동 매핑도 이 캐시에 저장됨.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from bookips.config import get_settings

logger = logging.getLogger(__name__)

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
        """ISBN 매핑 저장 (upsert)"""
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

    def delete_mapping(self, usage_isbn: str) -> bool:
        """매핑 삭제. True if deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM isbn_mappings WHERE usage_isbn = ?", (usage_isbn,)
            )
            conn.commit()
        return cursor.rowcount > 0

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
        """서지정보 캐시 저장 (upsert)"""
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

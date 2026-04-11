"""네이버 책 검색 API 클라이언트

국립중앙도서관 API의 보조 소스로 사용.
도서명에 학년/레벨 정보가 더 정확하게 포함됨.

API 문서: https://developers.naver.com/docs/serviceapi/search/book/book.md
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from bookips.models import BookMetadata

logger = logging.getLogger(__name__)

NAVER_API_URL = "https://openapi.naver.com/v1/search/book_adv.json"


class NaverBookClient:
    """네이버 책 검색 API 클라이언트"""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self._client_id = client_id or os.getenv("NAVER_CLIENT_ID", "")
        self._client_secret = client_secret or os.getenv("NAVER_CLIENT_SECRET", "")
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def search_by_isbn(self, isbn: str) -> Optional[BookMetadata]:
        """ISBN으로 도서 검색 → 정확한 도서명 반환"""
        if not self.is_configured:
            return None

        raw = isbn.replace("-", "").strip()
        params = {"d_isbn": raw, "display": 1}

        try:
            resp = self._request(params)
        except Exception as e:
            logger.warning("네이버 ISBN 검색 실패 %s: %s", isbn, e)
            return None

        items = resp.get("items", [])
        if not items:
            return None

        return self._parse_item(items[0], isbn)

    def search_by_title(self, title: str, display: int = 10) -> list[BookMetadata]:
        """도서명으로 검색"""
        if not self.is_configured or not title:
            return []

        # 핵심 키워드만 (너무 길면 검색 정확도 하락)
        import re
        clean = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()[:30].strip()
        params = {"d_titl": clean, "display": display}

        try:
            resp = self._request(params)
        except Exception as e:
            logger.warning("네이버 제목 검색 실패: %s", e)
            return []

        items = resp.get("items", [])
        return [self._parse_item(item) for item in items]

    def _request(self, params: dict) -> dict:
        headers = {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
        }
        resp = self._session.get(NAVER_API_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_item(item: dict, isbn_hint: str = "") -> BookMetadata:
        # 네이버 API 응답에서 HTML 태그 제거
        import re
        title = re.sub(r'<[^>]+>', '', item.get("title", ""))
        author = re.sub(r'<[^>]+>', '', item.get("author", ""))
        publisher = re.sub(r'<[^>]+>', '', item.get("publisher", ""))

        # ISBN: 네이버는 "isbn" 필드에 "ISBN10 ISBN13" 형태로 반환
        isbn_field = item.get("isbn", "")
        isbn13 = ""
        for part in isbn_field.split():
            if len(part) == 13:
                isbn13 = part
                break

        return BookMetadata(
            ea_isbn=isbn13 or isbn_hint,
            title=title,
            author=author,
            publisher=publisher,
            publish_date=item.get("pubdate", ""),
        )

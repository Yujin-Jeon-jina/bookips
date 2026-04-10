"""국립중앙도서관 서지정보 오픈 API 클라이언트

API 문서: https://www.nl.go.kr/NL/contents/N31101030500.do
엔드포인트: https://www.nl.go.kr/seoji/SearchApi.do
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from bookips.config import get_settings
from bookips.models import BookMetadata

logger = logging.getLogger(__name__)


class NLApiError(Exception):
    """국립중앙도서관 API 오류"""


class NLApiClient:
    """국립중앙도서관 서지정보 API 클라이언트

    Note:
        API 응답 필드명은 실제 API 키로 테스트 후 확인 필요.
        현재 구현은 공식 문서 및 커뮤니티 사례 기반 추정값 사용.
        첫 실행 시 `bookips/isbn/nl_api.py`의 필드명 매핑을 실제 응답에 맞게 조정.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        settings = get_settings()
        self._key = api_key or settings.nl_api_key
        self._base_url = settings.nl_api.base_url
        self._result_style = settings.nl_api.result_style
        self._page_size = settings.nl_api.page_size
        self._delay = settings.nl_api.rate_limit_delay
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "BookIPS/0.1 (settlement-system)"

    def lookup_isbn(self, isbn: str) -> Optional[BookMetadata]:
        """단일 ISBN으로 서지정보 조회.

        Args:
            isbn: 조회할 ISBN (13자리 권장)

        Returns:
            BookMetadata 또는 None (조회 실패 / 결과 없음)
        """
        raw = isbn.replace("-", "").strip()
        params = {
            "cert_key": self._key,
            "result_style": self._result_style,
            "page_no": 1,
            "page_size": self._page_size,
            "isbn": raw,
        }

        try:
            resp = self._get(params)
        except NLApiError as e:
            logger.warning("ISBN 조회 실패 %s: %s", isbn, e)
            return None

        docs = resp.get("docs") or resp.get("result") or []
        if not docs:
            logger.debug("ISBN 조회 결과 없음: %s", isbn)
            return None

        return self._parse_doc(docs[0])

    def batch_lookup(self, isbns: list[str]) -> dict[str, Optional[BookMetadata]]:
        """여러 ISBN을 순차적으로 조회 (rate limit 준수).

        Returns:
            {isbn: BookMetadata 또는 None}
        """
        results: dict[str, Optional[BookMetadata]] = {}
        for isbn in isbns:
            results[isbn] = self.lookup_isbn(isbn)
            time.sleep(self._delay)
        return results

    def _get(self, params: dict) -> dict:
        """API GET 요청 (재시도 포함)"""
        last_exc: Exception = Exception("unknown")
        for attempt in range(3):
            try:
                resp = self._session.get(self._base_url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return data
            except requests.HTTPError as e:
                last_exc = e
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("API rate limit (429), %d초 후 재시도", wait)
                    time.sleep(wait)
                else:
                    raise NLApiError(f"HTTP {resp.status_code}: {e}") from e
            except (requests.RequestException, OSError) as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning("API 요청 오류 (attempt %d): %s, %d초 후 재시도", attempt + 1, e, wait)
                time.sleep(wait)

        raise NLApiError(f"API 요청 실패 (3회 재시도): {last_exc}") from last_exc

    @staticmethod
    def _parse_doc(doc: dict) -> BookMetadata:
        """API 응답 문서 → BookMetadata 변환.

        Note:
            필드명은 실제 API 응답에 맞게 조정 필요.
            공식 문서 기준 추정 필드명 사용 중.
        """
        # EA_ISBN, TITLE 등은 국립중앙도서관 API의 표준 필드명
        # 실제 응답과 다를 경우 아래 키를 수정
        return BookMetadata(
            ea_isbn=_first(doc, "EA_ISBN", "isbn", "ISBN", ""),
            title=_first(doc, "TITLE", "title", "TITLE_INFO", ""),
            author=_first(doc, "AUTHOR", "author", "WRITER", ""),
            publisher=_first(doc, "PUBLISHER", "publisher", "PUBL_PLACE", ""),
            publish_date=_first(doc, "PUBLISH_PREDATE", "PUBLISH_DATE", "pubdate", ""),
            set_isbn=_first(doc, "SET_ISBN", "set_isbn", ""),
            edition=_first(doc, "EDITION_STMT", "edition", ""),
            subject=_first(doc, "SUBJECT", "class_no", ""),
        )


def _first(doc: dict, *keys: str, default: str = "") -> str:
    """여러 키 중 첫 번째로 존재하는 값 반환"""
    for key in keys:
        val = doc.get(key)
        if val is not None:
            return str(val).strip()
    return default

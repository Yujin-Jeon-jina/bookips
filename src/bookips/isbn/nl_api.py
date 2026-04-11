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

    def search_by_title(self, title: str, publisher: str = "") -> list[BookMetadata]:
        """도서명으로 검색하여 관련 도서 목록 반환.

        사용 사례: 미매칭 ISBN의 다른 판본(개정판/구판) 찾기.
        """
        if not title:
            return []

        # 핵심 키워드만 추출 (너무 긴 제목은 검색 정확도 떨어짐)
        import re
        # 괄호 내용 제거, 앞 30자만
        clean = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()[:30].strip()

        params = {
            "cert_key": self._key,
            "result_style": self._result_style,
            "page_no": 1,
            "page_size": 20,
            "title": clean,
        }
        if publisher:
            params["publisher"] = publisher

        try:
            resp = self._get(params)
        except NLApiError as e:
            logger.warning("도서명 검색 실패 '%s': %s", clean, e)
            return []

        docs = resp.get("docs") or resp.get("result") or []
        results = [self._parse_doc(d) for d in docs]
        logger.debug("도서명 검색 '%s': %d건", clean, len(results))
        return results

    def find_related_isbns(
        self,
        isbn: str,
        contract_isbns: set[str],
    ) -> list[tuple[str, str]]:
        """미매칭 ISBN의 다른 판본 중 계약 목록에 있는 ISBN 찾기.

        1. ISBN으로 도서 정보 조회
        2. 도서명으로 관련 도서 검색
        3. 계약 ISBN 목록과 대조

        Returns:
            [(contract_isbn, 해당 도서 제목), ...] 매칭된 것만
        """
        # 1. 원본 도서 정보 조회
        metadata = self.lookup_isbn(isbn)
        if not metadata or not metadata.title:
            return []

        time.sleep(self._delay)

        # 2. 도서명으로 관련 도서 검색
        related = self.search_by_title(metadata.title, metadata.publisher)

        # 3. 계약 ISBN과 대조
        matches = []
        for book in related:
            norm = book.ea_isbn.replace("-", "").strip()
            if norm in contract_isbns and norm != isbn:
                matches.append((norm, book.title))

        if matches:
            logger.info(
                "ISBN %s (%s) → 계약 목록에서 관련 판본 %d건 발견",
                isbn, metadata.title[:20], len(matches),
            )

        return matches

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

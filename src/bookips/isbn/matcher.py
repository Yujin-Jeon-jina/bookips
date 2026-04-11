"""ISBN 다단계 매칭 엔진

사용 ISBN → 계약 ISBN 매핑을 5단계 캐스케이드 알고리즘으로 수행.

Stage 1: 직접 매칭 (ISBN-13 정규화 후 정확 일치)
Stage 2: SQLite 캐시 조회
Stage 3: SET_ISBN / 시리즈 매칭 (국립중앙도서관 API)
Stage 4: 도서명 + 저자 퍼지 매칭
Stage 5: 미매칭 → 수동 검토 대기
"""
from __future__ import annotations

import logging
from typing import Optional

from bookips.config import get_settings
from bookips.isbn.cache import ISBNCache
from bookips.isbn.nl_api import NLApiClient
from bookips.isbn.normalizer import normalize_isbn
from bookips.models import (
    BookMetadata,
    ContractBook,
    ISBNMatch,
    UnmatchedRecord,
)
from bookips.utils.text import attributes_compatible, combined_score, same_subject, title_similarity

logger = logging.getLogger(__name__)


class ISBNMatcher:
    """다단계 ISBN 매칭 엔진"""

    def __init__(
        self,
        contract_books: list[ContractBook],
        cache: Optional[ISBNCache] = None,
        api_client: Optional[NLApiClient] = None,
    ) -> None:
        self._contracts = contract_books
        self._cache = cache or ISBNCache()
        self._api = api_client or NLApiClient()
        self._settings = get_settings().matching

        # 계약 ISBN → ContractBook 인덱스
        self._isbn_index: dict[str, ContractBook] = {}
        for book in contract_books:
            norm = normalize_isbn(book.isbn)
            self._isbn_index[norm] = book

    def match(
        self,
        usage_isbn: str,
        publisher: str = "",
        book_name: str = "",
    ) -> ISBNMatch | UnmatchedRecord:
        """사용 ISBN에 대해 계약 ISBN 매칭 시도.

        Returns:
            ISBNMatch (매칭 성공) 또는 UnmatchedRecord (매칭 실패)
        """
        norm_isbn = normalize_isbn(usage_isbn)

        # Stage 1: 직접 매칭
        result = self._stage1_direct(norm_isbn)
        if result:
            return result

        # Stage 2: 캐시 조회
        result = self._stage2_cache(norm_isbn)
        if result:
            return result

        # Stage 3: SET_ISBN 매칭 (API 호출)
        metadata = self._get_metadata(norm_isbn)

        if metadata:
            result = self._stage3_set_isbn(norm_isbn, metadata)
            if result:
                return result

            # Stage 4: 퍼지 매칭
            result = self._stage4_fuzzy(norm_isbn, metadata, publisher)
            if result:
                return result

        # Stage 5: 미매칭
        return self._stage5_unmatched(norm_isbn, publisher, book_name, metadata)

    def batch_match(
        self,
        records: list[tuple[str, str, str]],
    ) -> tuple[list[ISBNMatch], list[UnmatchedRecord]]:
        """여러 ISBN 일괄 매칭.

        Args:
            records: [(usage_isbn, publisher, book_name), ...]

        Returns:
            (matches, unmatched)
        """
        matches: list[ISBNMatch] = []
        unmatched: list[UnmatchedRecord] = []

        for usage_isbn, publisher, book_name in records:
            result = self.match(usage_isbn, publisher, book_name)
            if isinstance(result, ISBNMatch):
                matches.append(result)
            else:
                unmatched.append(result)

        logger.info(
            "매칭 결과: 성공 %d / 실패 %d (총 %d)",
            len(matches), len(unmatched), len(records),
        )
        return matches, unmatched

    # ─── Stage 1: 직접 매칭 ─────────────────────────────────────

    def _stage1_direct(self, norm_isbn: str) -> Optional[ISBNMatch]:
        """ISBN-13 정규화 후 정확히 일치하는지 확인"""
        book = self._isbn_index.get(norm_isbn)
        if book:
            logger.debug("Stage 1 직접 매칭: %s → %s", norm_isbn, book.isbn)
            return ISBNMatch(
                usage_isbn=norm_isbn,
                contract_isbn=book.isbn,
                contract_book=book,
                match_method="direct",
                confidence=1.0,
            )
        return None

    # ─── Stage 2: 캐시 조회 ─────────────────────────────────────

    def _stage2_cache(self, norm_isbn: str) -> Optional[ISBNMatch]:
        """SQLite 캐시에서 기존 매핑 검색"""
        cached = self._cache.get_mapping(norm_isbn)
        if cached:
            contract_isbn = cached["contract_isbn"]
            book = self._isbn_index.get(contract_isbn)
            if book:
                logger.debug("Stage 2 캐시: %s → %s", norm_isbn, contract_isbn)
                return ISBNMatch(
                    usage_isbn=norm_isbn,
                    contract_isbn=contract_isbn,
                    contract_book=book,
                    match_method="cache",
                    confidence=cached["confidence"],
                )
        return None

    # ─── Stage 3: SET_ISBN 매칭 ────────────────────────────────

    def _stage3_set_isbn(
        self, norm_isbn: str, metadata: BookMetadata
    ) -> Optional[ISBNMatch]:
        """SET_ISBN이 같은 계약 도서 탐색"""
        if not metadata.set_isbn:
            return None

        for book in self._contracts:
            # 계약 도서의 SET_ISBN도 API로 조회 필요 → 캐시에서 확인
            cached_meta = self._cache.get_metadata(normalize_isbn(book.isbn))
            if cached_meta and cached_meta.get("set_isbn") == metadata.set_isbn:
                logger.debug(
                    "Stage 3 SET_ISBN: %s → %s (SET: %s)",
                    norm_isbn, book.isbn, metadata.set_isbn,
                )
                match = ISBNMatch(
                    usage_isbn=norm_isbn,
                    contract_isbn=book.isbn,
                    contract_book=book,
                    match_method="set_isbn",
                    confidence=0.95,
                )
                self._cache.save_mapping(norm_isbn, book.isbn, "set_isbn", 0.95)
                return match
        return None

    # ─── Stage 4: 퍼지 매칭 ────────────────────────────────────

    def _stage4_fuzzy(
        self,
        norm_isbn: str,
        metadata: BookMetadata,
        publisher: str = "",
    ) -> Optional[ISBNMatch]:
        """국립중앙도서관 API 서지정보 기반 퍼지 매칭.

        API에서 조회한 정확한 도서명을 사용하여 계약도서와 비교.
        API 조회 실패 시 매칭하지 않음 (오매칭 방지).
        """
        if not metadata.title:
            logger.debug("Stage 4 스킵: API 도서명 없음 (%s)", norm_isbn)
            return None

        best_score = 0.0
        best_book: Optional[ContractBook] = None

        for book in self._contracts:
            # 과목 필터: 과목이 다르면 스킵
            if not same_subject(metadata.title, book.title):
                continue

            # 핵심 속성 필터: 학년/레벨/권수가 다르면 스킵
            if not attributes_compatible(metadata.title, book.title):
                continue

            # 같은 출판사 우선
            bonus = self._settings.same_publisher_bonus if (
                publisher and book.publisher == publisher
            ) else 0.0

            score = combined_score(
                metadata.title, book.title,
                metadata.author, "",
            ) + bonus

            if score > best_score:
                best_score = score
                best_book = book

        if best_book and best_score >= self._settings.combined_threshold:
            logger.debug(
                "Stage 4 퍼지: %s → %s (%.2f) [%s ↔ %s]",
                norm_isbn, best_book.isbn, best_score,
                metadata.title, best_book.title,
            )
            match = ISBNMatch(
                usage_isbn=norm_isbn,
                contract_isbn=best_book.isbn,
                contract_book=best_book,
                match_method="fuzzy",
                confidence=min(best_score, 1.0),
            )
            self._cache.save_mapping(
                norm_isbn, best_book.isbn, "fuzzy", min(best_score, 1.0)
            )
            return match

        return None

    # ─── Stage 5: 미매칭 ───────────────────────────────────────

    def _stage5_unmatched(
        self,
        norm_isbn: str,
        publisher: str,
        book_name: str,
        metadata: Optional[BookMetadata],
    ) -> UnmatchedRecord:
        """매칭 실패 → 후보 목록과 함께 반환"""
        candidates: list[tuple[ContractBook, float]] = []

        if metadata and metadata.title:
            scored = []
            for book in self._contracts:
                # 과목 필터
                if not same_subject(metadata.title, book.title):
                    continue
                # 핵심 속성 필터: 학년/레벨/권수 다르면 제외
                if not attributes_compatible(metadata.title, book.title):
                    continue

                bonus = self._settings.same_publisher_bonus if (
                    publisher and book.publisher == publisher
                ) else 0.0
                score = title_similarity(metadata.title, book.title) + bonus
                if score >= 0.80:
                    scored.append((book, min(score, 1.0)))

            scored.sort(key=lambda x: x[1], reverse=True)
            candidates = scored[:3]

        logger.debug("Stage 5 미매칭: %s (%s) — 후보 %d개", norm_isbn, book_name, len(candidates))

        return UnmatchedRecord(
            usage_isbn=norm_isbn,
            publisher=publisher,
            book_name=book_name,
            usage_count=0,
            unit_price=0,
            metadata=metadata,
            candidates=candidates,
        )

    # ─── 헬퍼 ──────────────────────────────────────────────────

    def _get_metadata(self, norm_isbn: str) -> Optional[BookMetadata]:
        """API 또는 캐시에서 서지정보 조회"""
        # 캐시 확인
        cached = self._cache.get_metadata(norm_isbn)
        if cached:
            return BookMetadata(
                ea_isbn=norm_isbn,
                title=cached.get("title", ""),
                author=cached.get("author", ""),
                publisher=cached.get("publisher", ""),
                set_isbn=cached.get("set_isbn", ""),
                edition=cached.get("edition", ""),
            )

        # API 호출
        metadata = self._api.lookup_isbn(norm_isbn)
        if metadata:
            self._cache.save_metadata(
                isbn=norm_isbn,
                title=metadata.title,
                author=metadata.author,
                publisher=metadata.publisher,
                set_isbn=metadata.set_isbn,
                edition=metadata.edition,
            )
        return metadata

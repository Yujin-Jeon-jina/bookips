"""계약도서 시트 읽기

계약도서 시트(MATHPRESSO CONTRACTED IP LIST_2026)에서
출판사별 계약 ISBN, 도서명, 단가 등을 읽어 ContractBook 리스트로 반환.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from bookips.config import get_settings
from bookips.isbn.normalizer import normalize_isbn
from bookips.models import ContractBook
from bookips.sheets.client import get_google_client

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> Optional[date]:
    """날짜 문자열 → date 변환 (여러 형식 시도)"""
    if not value or not value.strip():
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_price(value: str) -> int:
    """가격 문자열 → int 변환. '₩19,000' → 19000"""
    if not value:
        return 0
    cleaned = value.replace("₩", "").replace("\\", "").replace(",", "").replace("원", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        logger.warning("가격 파싱 실패: %r", value)
        return 0


def read_contract_books(publisher_filter: Optional[str] = None, active_only: bool = True) -> list[ContractBook]:
    """계약도서 시트에서 전체 또는 특정 출판사의 계약도서 목록 읽기.

    Args:
        publisher_filter: 특정 출판사명으로 필터링. None이면 전체.
        active_only: True면 현재 날짜 기준 유효한 계약만 반환.

    Returns:
        ContractBook 리스트
    """
    settings = get_settings()
    cfg = settings.contract
    client = get_google_client()

    all_values = client.get_all_values(cfg.spreadsheet_id, cfg.worksheet)

    # 헤더 행 건너뛰기 (header_rows 수만큼)
    data_rows = all_values[cfg.header_rows:]

    books: list[ContractBook] = []
    cols = cfg.columns

    for row_idx, row in enumerate(data_rows, start=cfg.header_rows + 1):
        # 빈 행 건너뛰기
        if not row or len(row) <= max(cols.isbn, cols.publisher, cols.title):
            continue

        raw_isbn = row[cols.isbn].strip() if len(row) > cols.isbn else ""
        publisher = row[cols.publisher].strip() if len(row) > cols.publisher else ""
        title = row[cols.title].strip() if len(row) > cols.title else ""

        if not raw_isbn or not publisher:
            continue

        # 출판사 필터
        if publisher_filter and publisher != publisher_filter:
            continue

        unit_price_str = row[cols.unit_price] if len(row) > cols.unit_price else ""
        start_date_str = row[cols.start_date] if len(row) > cols.start_date else ""
        end_date_str = row[cols.end_date] if len(row) > cols.end_date else ""

        book = ContractBook(
            isbn=normalize_isbn(raw_isbn),
            publisher=publisher,
            title=title,
            unit_price=_parse_price(unit_price_str),
            start_date=_parse_date(start_date_str),
            end_date=_parse_date(end_date_str),
            raw_isbn=raw_isbn,
        )

        # 계약 기간 필터: 현재일이 시작일~종료일 사이인 것만
        if active_only:
            today = date.today()
            if not book.is_active(today):
                continue

        books.append(book)

    total_before_filter = row_idx - cfg.header_rows
    logger.info(
        "계약도서 %d건 로드 (전체 %d건 중 유효 계약만, 필터: %s)",
        len(books),
        total_before_filter,
        publisher_filter or "전체",
    )
    return books


def get_publisher_list() -> list[str]:
    """계약도서 시트에서 고유 출판사 목록 반환 (정렬)"""
    books = read_contract_books()
    publishers = sorted(set(b.publisher for b in books))
    return publishers

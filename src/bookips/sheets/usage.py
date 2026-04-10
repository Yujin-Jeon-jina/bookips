"""사용량 시트 읽기 (Pivot 탭)

사용량 시트(2024 bookips)의 Pivot 탭에서
출판사별 사용 ISBN, 사용자수, 단가 데이터를 읽어 UsageRecord 리스트로 반환.

전제: 사용자가 시작일/종료일 설정 후 BigQuery 새로고침을 완료한 상태.
"""
from __future__ import annotations

import logging
from typing import Optional

from bookips.config import get_settings
from bookips.isbn.normalizer import normalize_isbn
from bookips.models import UsageRecord
from bookips.sheets.client import get_google_client

logger = logging.getLogger(__name__)


def _parse_int(value: str) -> int:
    """숫자 문자열 → int 변환. 빈 문자열이나 비정상값은 0"""
    if not value or not value.strip():
        return 0
    cleaned = value.replace(",", "").replace("₩", "").replace("\\", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def read_usage_data(publisher_filter: Optional[str] = None) -> list[UsageRecord]:
    """사용량 Pivot 탭에서 데이터 읽기.

    Args:
        publisher_filter: 특정 출판사명으로 필터링. None이면 전체.

    Returns:
        UsageRecord 리스트
    """
    settings = get_settings()
    cfg = settings.usage
    client = get_google_client()

    all_values = client.get_all_values(cfg.spreadsheet_id, cfg.worksheet)

    # Pivot 탭 상단에서 정산 기간 읽기 (행1~3: 연도, 시작일, 종료일)
    period = ""
    if len(all_values) > 2:
        # 행3(index 2)에 종료일이 있음 → YYYY-MM 형식으로 변환
        end_date_str = all_values[2][2] if len(all_values[2]) > 2 else ""  # C3
        if end_date_str and "-" in end_date_str:
            parts = end_date_str.split("-")
            if len(parts) >= 2:
                period = f"{parts[0]}-{parts[1]}"

    # 데이터 행 (data_start_row부터)
    data_rows = all_values[cfg.data_start_row:]
    cols = cfg.columns

    records: list[UsageRecord] = []

    for row in data_rows:
        if not row or len(row) <= max(cols.isbn, cols.publisher):
            continue

        publisher = row[cols.publisher].strip() if len(row) > cols.publisher else ""
        raw_isbn = row[cols.isbn].strip() if len(row) > cols.isbn else ""
        book_name = row[cols.book_name].strip() if len(row) > cols.book_name else ""

        if not raw_isbn or not publisher:
            continue

        # 출판사 필터
        if publisher_filter and publisher != publisher_filter:
            continue

        usage_count_str = row[cols.usage_count] if len(row) > cols.usage_count else ""
        unit_price_str = row[cols.unit_price] if len(row) > cols.unit_price else ""
        amount_str = row[cols.amount] if len(row) > cols.amount else ""
        authorized_str = row[cols.authorized] if len(row) > cols.authorized else ""

        record = UsageRecord(
            isbn=normalize_isbn(raw_isbn),
            publisher=publisher,
            book_name=book_name,
            usage_count=_parse_int(usage_count_str),
            unit_price=_parse_int(unit_price_str),
            amount=_parse_int(amount_str),
            authorized=authorized_str.strip(),
        )
        records.append(record)

    logger.info(
        "사용량 %d건 로드 (기간: %s, 필터: %s)",
        len(records),
        period or "미확인",
        publisher_filter or "전체",
    )
    return records


def get_usage_period() -> str:
    """현재 Pivot 탭에 설정된 정산 기간 반환 (YYYY-MM 형식)"""
    settings = get_settings()
    cfg = settings.usage
    client = get_google_client()

    all_values = client.get_all_values(cfg.spreadsheet_id, cfg.worksheet)

    if len(all_values) > 2 and len(all_values[2]) > 2:
        end_date_str = all_values[2][2]  # C3 = 종료일
        if end_date_str and "-" in end_date_str:
            parts = end_date_str.split("-")
            if len(parts) >= 2:
                return f"{parts[0]}-{parts[1]}"
    return ""

"""정산 오케스트레이터: 전체 워크플로우 조율

1. 계약도서 읽기
2. 사용량 읽기
3. ISBN 매칭
4. 계약 ISBN별 집계
5. 정산 파일 생성
6. 메인 시트 Link 업데이트
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from bookips.config import get_settings
from bookips.isbn.cache import ISBNCache
from bookips.isbn.matcher import ISBNMatcher
from bookips.isbn.nl_api import NLApiClient
from bookips.isbn.normalizer import normalize_isbn
from bookips.models import (
    ContractBook,
    ISBNMatch,
    SettlementResult,
    SettlementRow,
    UnmatchedRecord,
    UsageRecord,
)
from bookips.sheets.client import get_google_client
from bookips.sheets.contract import read_contract_books
from bookips.sheets.settlement import (
    copy_settlement_file,
    find_month_column,
    find_publisher_block,
    get_evidence_link,
    update_evidence_link,
    write_settlement_data,
)
from bookips.sheets.usage import read_usage_data, get_usage_period

logger = logging.getLogger(__name__)


class SettlementEngine:
    """정산 처리 엔진"""

    def __init__(self) -> None:
        self._cache = ISBNCache()
        self._api = NLApiClient()

    def run_settlement(
        self,
        publisher: str,
        year: int,
        month: int,
        dry_run: bool = False,
    ) -> SettlementResult:
        """특정 출판사의 월별 정산 실행.

        Args:
            publisher: 출판사명
            year: 연도 (e.g., 2026)
            month: 월 (e.g., 3)
            dry_run: True면 시트에 쓰지 않고 결과만 반환

        Returns:
            SettlementResult
        """
        period = f"{year}-{month:02d}"
        logger.info("정산 시작: %s %s", publisher, period)

        # 1. 계약도서 읽기
        contract_books = read_contract_books(publisher_filter=publisher)
        if not contract_books:
            logger.warning("계약도서 없음: %s", publisher)
            return SettlementResult(publisher=publisher, period=period)

        logger.info("계약도서 %d건 로드", len(contract_books))

        # 2. 사용량 읽기
        usage_records = read_usage_data(publisher_filter=publisher)
        if not usage_records:
            logger.warning("사용량 데이터 없음: %s", publisher)
            return SettlementResult(publisher=publisher, period=period)

        logger.info("사용량 %d건 로드", len(usage_records))

        # 3. ISBN 매칭
        matcher = ISBNMatcher(
            contract_books=contract_books,
            cache=self._cache,
            api_client=self._api,
        )

        match_inputs = [
            (rec.isbn, rec.publisher, rec.book_name)
            for rec in usage_records
        ]
        matches, unmatched_list = matcher.batch_match(match_inputs)

        # 사용량 정보를 UnmatchedRecord에 채우기
        usage_by_isbn = {normalize_isbn(r.isbn): r for r in usage_records}
        for um in unmatched_list:
            rec = usage_by_isbn.get(um.usage_isbn)
            if rec:
                um.usage_count = rec.usage_count
                um.unit_price = rec.unit_price

        # 4. 계약 ISBN별 집계
        settlement_rows = self._aggregate(matches, usage_records, period)

        logger.info(
            "집계 결과: 정산 %d건, 미매칭 %d건, 총액 %s원",
            len(settlement_rows),
            len(unmatched_list),
            f"{sum(r.amount for r in settlement_rows):,}",
        )

        result = SettlementResult(
            publisher=publisher,
            period=period,
            rows=settlement_rows,
            unmatched=unmatched_list,
        )

        # 5-6. 시트 쓰기 (dry_run이 아닐 때)
        if not dry_run and settlement_rows:
            try:
                new_file_url = self._write_to_sheets(
                    publisher, year, month, settlement_rows
                )
                result.new_file_url = new_file_url
            except Exception as e:
                logger.error("시트 쓰기 실패: %s", e)

        return result

    def preview_settlement(
        self,
        publisher: str,
    ) -> SettlementResult:
        """정산 미리보기 (시트 쓰기 없이 매칭 결과만)"""
        period = get_usage_period()
        if not period:
            period = "미확인"

        year = int(period.split("-")[0]) if "-" in period else 2026
        month = int(period.split("-")[1]) if "-" in period else 1

        return self.run_settlement(publisher, year, month, dry_run=True)

    def _aggregate(
        self,
        matches: list[ISBNMatch],
        usage_records: list[UsageRecord],
        period: str,
    ) -> list[SettlementRow]:
        """매칭 결과를 계약 ISBN별로 집계.

        여러 사용 ISBN이 같은 계약 ISBN에 매핑되면 사용건수를 합산.
        """
        # usage ISBN → usage record 매핑
        usage_by_isbn: dict[str, UsageRecord] = {}
        for rec in usage_records:
            usage_by_isbn[normalize_isbn(rec.isbn)] = rec

        # 계약 ISBN별 사용건수 합산
        contract_usage: dict[str, int] = defaultdict(int)
        contract_match: dict[str, ISBNMatch] = {}

        for match in matches:
            rec = usage_by_isbn.get(match.usage_isbn)
            usage_count = rec.usage_count if rec else 0
            contract_usage[match.contract_isbn] += usage_count
            # 첫 매칭 정보 저장 (동일 계약 ISBN에 여러 사용 ISBN이 매핑될 수 있음)
            if match.contract_isbn not in contract_match:
                contract_match[match.contract_isbn] = match

        # SettlementRow 생성
        rows: list[SettlementRow] = []
        for contract_isbn, total_count in contract_usage.items():
            match = contract_match[contract_isbn]
            book = match.contract_book
            rows.append(SettlementRow(
                period=period,
                publisher=book.publisher,
                contract_isbn=contract_isbn,
                title=book.title,
                usage_count=total_count,
                unit_price=book.unit_price,
                amount=total_count * book.unit_price,
                match_method=match.match_method,
            ))

        # 사용건수 내림차순 정렬
        rows.sort(key=lambda r: r.usage_count, reverse=True)
        return rows

    def _write_to_sheets(
        self,
        publisher: str,
        year: int,
        month: int,
        rows: list[SettlementRow],
    ) -> str:
        """정산 결과를 Google Sheets에 반영.

        1. 전월 Link에서 파일 ID 추출
        2. 파일 복사
        3. 데이터 쓰기
        4. Link 업데이트
        """
        settings = get_settings()
        client = get_google_client()

        # 메인 시트 전체 값 로드 (탭 이름 fallback)
        try:
            all_values = client.get_all_values(
                settings.settlement.spreadsheet_id,
                settings.settlement.summary_worksheet,
            )
        except Exception:
            logger.warning("워크시트 '%s' 찾기 실패, 첫 번째 시트 사용", settings.settlement.summary_worksheet)
            ss = client.open_spreadsheet(settings.settlement.spreadsheet_id)
            ws = ss.sheet1
            all_values = ws.get_all_values()

        # 출판사 블록 찾기
        block = find_publisher_block(all_values, publisher)
        if not block:
            raise RuntimeError(f"정산 메인 시트에서 '{publisher}' 블록을 찾을 수 없습니다")

        # 전월 컬럼 찾기
        prev_month = month - 1
        prev_year = year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1

        item_row_values = all_values[block["item_row"]]
        prev_col = find_month_column(item_row_values, prev_year, prev_month)
        curr_col = find_month_column(item_row_values, year, month)

        if prev_col is None:
            raise RuntimeError(
                f"전월({prev_year}-{prev_month:02d}) 컬럼을 찾을 수 없습니다"
            )

        # 전월 Link에서 파일 ID 추출
        prev_link = get_evidence_link(
            settings.settlement.spreadsheet_id,
            settings.settlement.summary_worksheet,
            block["evidence_row"],
            prev_col,
        )

        if not prev_link:
            raise RuntimeError(f"전월 증빙 Link가 없습니다 (row={block['evidence_row']}, col={prev_col})")

        prev_file_id = client.get_file_id_from_url(prev_link)
        if not prev_file_id:
            raise RuntimeError(f"전월 Link에서 파일 ID를 추출할 수 없습니다: {prev_link}")

        # 파일 복사
        new_file_id = copy_settlement_file(prev_file_id, publisher, year, month)

        # 데이터 쓰기
        write_settlement_data(new_file_id, rows)

        # Link 업데이트 (당월 컬럼이 있으면)
        if curr_col is not None:
            update_evidence_link(
                settings.settlement.spreadsheet_id,
                settings.settlement.summary_worksheet,
                block["evidence_row"],
                curr_col,
                new_file_id,
            )

        new_url = client.get_spreadsheet_url(new_file_id)
        logger.info("정산 완료: %s → %s", publisher, new_url)
        return new_url

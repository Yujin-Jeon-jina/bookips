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
    SourceISBN,
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
    get_mg_balance,
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
        prev_file_url: str = "",
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
                    publisher, year, month, settlement_rows, prev_file_url
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

        # 계약 ISBN별 사용건수 합산 + 출처 추적
        contract_usage: dict[str, int] = defaultdict(int)
        contract_match: dict[str, ISBNMatch] = {}
        contract_sources: dict[str, list[SourceISBN]] = defaultdict(list)

        for match in matches:
            rec = usage_by_isbn.get(match.usage_isbn)
            usage_count = rec.usage_count if rec else 0
            contract_usage[match.contract_isbn] += usage_count

            # 출처 정보 기록
            contract_sources[match.contract_isbn].append(SourceISBN(
                usage_isbn=match.usage_isbn,
                usage_count=usage_count,
                match_method=match.match_method,
                confidence=match.confidence,
                book_name=rec.book_name if rec else "",
            ))

            if match.contract_isbn not in contract_match:
                contract_match[match.contract_isbn] = match

        # SettlementRow 생성
        rows: list[SettlementRow] = []
        for contract_isbn, total_count in contract_usage.items():
            match = contract_match[contract_isbn]
            book = match.contract_book
            sources = contract_sources[contract_isbn]
            rows.append(SettlementRow(
                period=period,
                publisher=book.publisher,
                contract_isbn=contract_isbn,
                title=book.title,
                usage_count=total_count,
                unit_price=book.unit_price,
                amount=total_count * book.unit_price,
                match_method=match.match_method,
                sources=sources,
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
        prev_file_url: str = "",
    ) -> str:
        """정산 결과를 Google Sheets에 반영.

        사용자가 전월 파일 URL을 제공하면 그 파일을 복사.
        제공하지 않으면 정산 메인 시트에서 전월 Link를 자동 탐색.
        """
        settings = get_settings()
        client = get_google_client()

        # 전월 파일 ID 결정
        prev_file_id = None

        # 1순위: 사용자가 직접 입력한 전월 파일 URL
        if prev_file_url and prev_file_url.strip():
            prev_file_id = client.get_file_id_from_url(prev_file_url.strip())
            if prev_file_id:
                logger.info("사용자 입력 전월 파일 사용: %s", prev_file_id)

        # 2순위: 정산 메인 시트에서 자동 탐색
        if not prev_file_id:
            try:
                all_values = client.get_all_values(
                    settings.settlement.spreadsheet_id,
                    settings.settlement.summary_worksheet,
                )
                block = find_publisher_block(all_values, publisher)
                if block:
                    prev_month = month - 1
                    prev_year = year
                    if prev_month == 0:
                        prev_month = 12
                        prev_year -= 1

                    item_row_values = all_values[block["item_row"]]
                    prev_col = find_month_column(item_row_values, prev_year, prev_month)

                    if prev_col is not None:
                        prev_link = get_evidence_link(
                            settings.settlement.spreadsheet_id,
                            settings.settlement.summary_worksheet,
                            block["evidence_row"],
                            prev_col,
                        )
                        if prev_link:
                            prev_file_id = client.get_file_id_from_url(prev_link)
            except Exception as e:
                logger.warning("메인 시트 자동 탐색 실패: %s", e)

        if not prev_file_id:
            raise RuntimeError(
                "전월 정산 파일을 찾을 수 없습니다. '전월 정산파일 URL'을 직접 입력해 주세요."
            )

        # 전월 MG 잔액 읽기
        prev_mg_balance = None
        try:
            all_vals = client.get_all_values(
                settings.settlement.spreadsheet_id,
                settings.settlement.summary_worksheet,
            )
            blk = find_publisher_block(all_vals, publisher)
            if blk:
                item_vals = all_vals[blk["item_row"]]
                prev_month = month - 1
                prev_year = year
                if prev_month == 0:
                    prev_month = 12
                    prev_year -= 1
                pcol = find_month_column(item_vals, prev_year, prev_month)
                if pcol is not None:
                    prev_mg_balance = get_mg_balance(all_vals, blk, pcol)
                    if prev_mg_balance is not None:
                        logger.info("전월 MG 잔액: %s원", f"{prev_mg_balance:,}")
        except Exception as e:
            logger.warning("MG 잔액 조회 실패: %s", e)

        # 파일 복사
        new_file_id = copy_settlement_file(prev_file_id, publisher, year, month)

        # 데이터 쓰기 (합계 + MG 잔액 포함)
        write_settlement_data(new_file_id, rows, prev_mg_balance=prev_mg_balance)

        # 메인 시트 Link 업데이트 시도
        try:
            all_values = client.get_all_values(
                settings.settlement.spreadsheet_id,
                settings.settlement.summary_worksheet,
            )
            block = find_publisher_block(all_values, publisher)
            if block:
                item_row_values = all_values[block["item_row"]]
                curr_col = find_month_column(item_row_values, year, month)
                if curr_col is not None:
                    update_evidence_link(
                        settings.settlement.spreadsheet_id,
                        settings.settlement.summary_worksheet,
                        block["evidence_row"],
                        curr_col,
                        new_file_id,
                    )
        except Exception as e:
            logger.warning("메인 시트 Link 업데이트 스킵: %s", e)

        new_url = client.get_spreadsheet_url(new_file_id)
        logger.info("정산 완료: %s → %s", publisher, new_url)
        return new_url

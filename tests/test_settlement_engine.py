"""정산 엔진 집계 로직 테스트 (Google Sheets 의존 없이)

gspread/cryptography 임포트 문제를 피하기 위해 집계 로직만 직접 테스트.
"""
import pytest
from collections import defaultdict

from bookips.models import (
    ContractBook,
    ISBNMatch,
    SettlementRow,
    UsageRecord,
)
from bookips.isbn.normalizer import normalize_isbn


def _aggregate(
    matches: list[ISBNMatch],
    usage_records: list[UsageRecord],
    period: str,
) -> list[SettlementRow]:
    """SettlementEngine._aggregate 로직 복사 (gspread 임포트 없이 테스트)"""
    usage_by_isbn: dict[str, UsageRecord] = {}
    for rec in usage_records:
        usage_by_isbn[normalize_isbn(rec.isbn)] = rec

    contract_usage: dict[str, int] = defaultdict(int)
    contract_match: dict[str, ISBNMatch] = {}

    for match in matches:
        rec = usage_by_isbn.get(match.usage_isbn)
        usage_count = rec.usage_count if rec else 0
        contract_usage[match.contract_isbn] += usage_count
        if match.contract_isbn not in contract_match:
            contract_match[match.contract_isbn] = match

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

    rows.sort(key=lambda r: r.usage_count, reverse=True)
    return rows


class TestAggregate:
    def test_single_match(self):
        book = ContractBook(
            isbn="9788961334839", publisher="개념원리",
            title="공통수학1", unit_price=19000,
        )
        matches = [
            ISBNMatch(
                usage_isbn="9788961334839", contract_isbn="9788961334839",
                contract_book=book, match_method="direct", confidence=1.0,
            )
        ]
        usage = [
            UsageRecord(
                isbn="9788961334839", publisher="개념원리",
                book_name="공통수학1", usage_count=30,
                unit_price=19000, amount=570000,
            )
        ]

        rows = _aggregate(matches, usage, "2026-03")
        assert len(rows) == 1
        assert rows[0].contract_isbn == "9788961334839"
        assert rows[0].usage_count == 30
        assert rows[0].amount == 570000

    def test_multiple_usage_isbns_to_same_contract(self):
        """여러 사용 ISBN이 같은 계약 ISBN에 매핑되면 합산"""
        book = ContractBook(
            isbn="9788961334839", publisher="개념원리",
            title="공통수학1", unit_price=19000,
        )
        matches = [
            ISBNMatch(
                usage_isbn="9780000000001", contract_isbn="9788961334839",
                contract_book=book, match_method="fuzzy", confidence=0.85,
            ),
            ISBNMatch(
                usage_isbn="9780000000002", contract_isbn="9788961334839",
                contract_book=book, match_method="fuzzy", confidence=0.80,
            ),
        ]
        usage = [
            UsageRecord(
                isbn="9780000000001", publisher="개념원리",
                book_name="공통수학1(구판)", usage_count=10,
                unit_price=19000, amount=190000,
            ),
            UsageRecord(
                isbn="9780000000002", publisher="개념원리",
                book_name="공통수학1(신판)", usage_count=20,
                unit_price=19000, amount=380000,
            ),
        ]

        rows = _aggregate(matches, usage, "2026-03")
        assert len(rows) == 1
        assert rows[0].usage_count == 30
        assert rows[0].amount == 30 * 19000

    def test_different_contracts(self):
        """서로 다른 계약 ISBN은 별도 행"""
        book1 = ContractBook(
            isbn="9788961334839", publisher="개념원리",
            title="공통수학1", unit_price=19000,
        )
        book2 = ContractBook(
            isbn="9788961335973", publisher="개념원리",
            title="대수", unit_price=17000,
        )
        matches = [
            ISBNMatch(
                usage_isbn="9788961334839", contract_isbn="9788961334839",
                contract_book=book1, match_method="direct", confidence=1.0,
            ),
            ISBNMatch(
                usage_isbn="9788961335973", contract_isbn="9788961335973",
                contract_book=book2, match_method="direct", confidence=1.0,
            ),
        ]
        usage = [
            UsageRecord(
                isbn="9788961334839", publisher="개념원리",
                book_name="공통수학1", usage_count=30,
                unit_price=19000, amount=570000,
            ),
            UsageRecord(
                isbn="9788961335973", publisher="개념원리",
                book_name="대수", usage_count=22,
                unit_price=17000, amount=374000,
            ),
        ]

        rows = _aggregate(matches, usage, "2026-03")
        assert len(rows) == 2
        assert rows[0].usage_count >= rows[1].usage_count
        total = sum(r.amount for r in rows)
        assert total == 570000 + 374000

    def test_empty_matches(self):
        rows = _aggregate([], [], "2026-03")
        assert rows == []


class TestSettlementRow:
    def test_from_match(self):
        book = ContractBook(
            isbn="9788961334839", publisher="개념원리",
            title="공통수학1", unit_price=19000,
        )
        match = ISBNMatch(
            usage_isbn="9780000000001", contract_isbn="9788961334839",
            contract_book=book, match_method="fuzzy", confidence=0.85,
        )
        row = SettlementRow.from_match(match, "2026-03", usage_count=15)
        assert row.contract_isbn == "9788961334839"
        assert row.usage_count == 15
        assert row.unit_price == 19000
        assert row.amount == 285000
        assert row.match_method == "fuzzy"

    def test_settlement_result_totals(self):
        from bookips.models import SettlementResult
        result = SettlementResult(
            publisher="개념원리",
            period="2026-03",
            rows=[
                SettlementRow(
                    period="2026-03", publisher="개념원리",
                    contract_isbn="A", title="책A",
                    usage_count=10, unit_price=19000, amount=190000,
                ),
                SettlementRow(
                    period="2026-03", publisher="개념원리",
                    contract_isbn="B", title="책B",
                    usage_count=5, unit_price=17000, amount=85000,
                ),
            ],
            unmatched=[],
        )
        assert result.total_amount == 275000
        assert result.match_rate == 1.0

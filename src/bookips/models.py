"""도메인 데이터 클래스"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ContractBook:
    """계약도서 시트의 한 행"""
    isbn: str               # 계약 ISBN (13자리로 정규화)
    publisher: str          # 출판사명
    title: str              # IP 교재명
    unit_price: int         # 교재 정가 (원)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    raw_isbn: str = ""      # 원본 ISBN (정규화 전)

    def is_active(self, target_date: date) -> bool:
        """계약 기간 유효 여부"""
        if self.start_date and target_date < self.start_date:
            return False
        if self.end_date and target_date > self.end_date:
            return False
        return True


@dataclass
class UsageRecord:
    """사용량 시트 Pivot 탭의 한 행"""
    isbn: str               # 실제 사용된 ISBN (계약 ISBN과 다를 수 있음)
    publisher: str          # 출판사명
    book_name: str          # contractedBook.bookName
    usage_count: int        # 사용자 수 (COUNTUNIQUE)
    unit_price: int         # 단가
    amount: int             # 사용자수 × 단가
    authorized: str = ""    # 미하가여부


@dataclass
class BookMetadata:
    """국립중앙도서관 API에서 조회한 도서 서지정보"""
    ea_isbn: str            # 개별 ISBN
    title: str              # 도서명
    author: str             # 저자
    publisher: str          # 출판사
    publish_date: str = ""  # 발행일
    set_isbn: str = ""      # 세트 ISBN
    edition: str = ""       # 판차 정보
    subject: str = ""       # 주제 분류


@dataclass
class ISBNMatch:
    """ISBN 매핑 결과"""
    usage_isbn: str
    contract_isbn: str
    contract_book: ContractBook
    match_method: str       # direct / cache / set_isbn / fuzzy / manual
    confidence: float       # 0.0 ~ 1.0

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.70


@dataclass
class SettlementRow:
    """개별 정산 파일 첫 번째 탭의 한 행"""
    period: str             # 정산 기간 (YYYY-MM)
    publisher: str          # 출판사
    contract_isbn: str      # 계약 ISBN
    title: str              # 교재명
    usage_count: int        # 등록 교재 수 (집계된 사용건수)
    unit_price: int         # 교재 정가
    amount: int             # 정산 금액 (usage_count × unit_price)
    match_method: str = ""  # 매칭 방법 (리포트용)

    @classmethod
    def from_match(cls, match: ISBNMatch, period: str, usage_count: int) -> "SettlementRow":
        book = match.contract_book
        amount = usage_count * book.unit_price
        return cls(
            period=period,
            publisher=book.publisher,
            contract_isbn=book.isbn,
            title=book.title,
            usage_count=usage_count,
            unit_price=book.unit_price,
            amount=amount,
            match_method=match.match_method,
        )


@dataclass
class UnmatchedRecord:
    """매칭 실패한 사용 ISBN 정보 (수동 검토 대기)"""
    usage_isbn: str
    publisher: str
    book_name: str
    usage_count: int
    unit_price: int
    metadata: Optional[BookMetadata] = None
    candidates: list[tuple[ContractBook, float]] = field(default_factory=list)
    # candidates: [(contract_book, similarity_score), ...]


@dataclass
class SettlementResult:
    """출판사별 정산 실행 결과"""
    publisher: str
    period: str
    rows: list[SettlementRow] = field(default_factory=list)
    unmatched: list[UnmatchedRecord] = field(default_factory=list)
    new_file_url: str = ""

    @property
    def total_amount(self) -> int:
        return sum(r.amount for r in self.rows)

    @property
    def match_rate(self) -> float:
        total = len(self.rows) + len(self.unmatched)
        return len(self.rows) / total if total > 0 else 0.0

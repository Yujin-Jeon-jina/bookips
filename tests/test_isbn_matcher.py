"""ISBN 매칭 엔진 테스트"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from bookips.isbn.cache import ISBNCache
from bookips.isbn.matcher import ISBNMatcher
from bookips.models import BookMetadata, ContractBook, ISBNMatch, UnmatchedRecord


@pytest.fixture
def contract_books():
    return [
        ContractBook(
            isbn="9788961334839",
            publisher="개념원리",
            title="개념원리 고등 공통수학1",
            unit_price=19000,
        ),
        ContractBook(
            isbn="9788961335973",
            publisher="개념원리",
            title="개념원리 대수(2026)",
            unit_price=17000,
        ),
        ContractBook(
            isbn="9791125337072",
            publisher="NE능률",
            title="Grammar Inside 그래머 인사이드 Level 1",
            unit_price=15500,
        ),
    ]


@pytest.fixture
def cache(tmp_path):
    return ISBNCache(db_path=tmp_path / "test.db")


@pytest.fixture
def mock_api():
    return MagicMock()


class TestStage1Direct:
    def test_exact_match(self, contract_books, cache, mock_api):
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9788961334839")
        assert isinstance(result, ISBNMatch)
        assert result.match_method == "direct"
        assert result.confidence == 1.0
        assert result.contract_isbn == "9788961334839"

    def test_hyphenated_isbn_match(self, contract_books, cache, mock_api):
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("978-89-61-334839")
        assert isinstance(result, ISBNMatch)
        assert result.match_method == "direct"

    def test_no_match(self, contract_books, cache, mock_api):
        mock_api.lookup_isbn.return_value = None
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000000")
        assert isinstance(result, UnmatchedRecord)


class TestStage2Cache:
    def test_cached_mapping(self, contract_books, cache, mock_api):
        # 캐시에 매핑 저장
        cache.save_mapping("9780000000001", "9788961334839", "manual", 1.0)

        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000001")
        assert isinstance(result, ISBNMatch)
        assert result.match_method == "cache"
        assert result.contract_isbn == "9788961334839"

    def test_cache_miss_proceeds_to_api(self, contract_books, cache, mock_api):
        mock_api.lookup_isbn.return_value = None
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000002")
        # API가 호출되어야 함
        mock_api.lookup_isbn.assert_called_once()
        assert isinstance(result, UnmatchedRecord)


class TestStage4Fuzzy:
    def test_fuzzy_match_by_title(self, contract_books, cache, mock_api):
        # API가 유사한 도서명을 반환
        mock_api.lookup_isbn.return_value = BookMetadata(
            ea_isbn="9780000000003",
            title="개념원리 고등 공통수학1(2025년 고1 적용)",  # 제목 유사
            author="홍성대",
            publisher="개념원리",
        )
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000003", publisher="개념원리")

        assert isinstance(result, ISBNMatch)
        assert result.match_method == "fuzzy"
        assert result.contract_isbn == "9788961334839"
        assert result.confidence >= 0.70

    def test_fuzzy_no_match_low_similarity(self, contract_books, cache, mock_api):
        mock_api.lookup_isbn.return_value = BookMetadata(
            ea_isbn="9780000000004",
            title="완전히 다른 책 제목",
            author="김아무개",
            publisher="다른출판사",
        )
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000004")

        assert isinstance(result, UnmatchedRecord)

    def test_publisher_bonus(self, contract_books, cache, mock_api):
        """같은 출판사 보너스 점수 적용"""
        mock_api.lookup_isbn.return_value = BookMetadata(
            ea_isbn="9780000000005",
            title="Grammar Inside Level 1",  # 약간 다른 제목
            author="",
            publisher="NE능률",
        )
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000005", publisher="NE능률")

        assert isinstance(result, ISBNMatch)
        assert result.contract_isbn == "9791125337072"


class TestStage5Unmatched:
    def test_unmatched_has_candidates(self, contract_books, cache, mock_api):
        mock_api.lookup_isbn.return_value = BookMetadata(
            ea_isbn="9780000000006",
            title="개념원리 고등 미적분",  # 부분 일치
            author="홍성대",
            publisher="개념원리",
        )
        matcher = ISBNMatcher(contract_books, cache, mock_api)
        result = matcher.match("9780000000006")

        if isinstance(result, UnmatchedRecord):
            # 후보가 있어야 함
            assert len(result.candidates) > 0
            # 후보는 유사도 내림차순
            scores = [s for _, s in result.candidates]
            assert scores == sorted(scores, reverse=True)


class TestBatchMatch:
    def test_batch_match(self, contract_books, cache, mock_api):
        mock_api.lookup_isbn.return_value = None
        matcher = ISBNMatcher(contract_books, cache, mock_api)

        records = [
            ("9788961334839", "개념원리", "개념원리 고등 공통수학1"),  # direct
            ("9780000000099", "기타", "모르는 책"),                    # unmatched
        ]
        matches, unmatched = matcher.batch_match(records)
        assert len(matches) == 1
        assert len(unmatched) == 1
        assert matches[0].match_method == "direct"

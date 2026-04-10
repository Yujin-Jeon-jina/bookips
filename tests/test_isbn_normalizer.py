"""ISBN 정규화 테스트"""
import pytest
from bookips.isbn.normalizer import (
    normalize_isbn,
    isbn10_to_isbn13,
    is_isbn10,
    is_isbn13,
    isbns_equal,
    strip_isbn,
)


class TestStripISBN:
    def test_removes_hyphens(self):
        assert strip_isbn("978-89-61-33483-9") == "9788961334839"

    def test_removes_spaces(self):
        assert strip_isbn("978 89 33483") == "9788933483"

    def test_strips_whitespace(self):
        assert strip_isbn("  9788961334839  ") == "9788961334839"


class TestIsISBN:
    def test_isbn13_valid(self):
        assert is_isbn13("9788961334839") is True

    def test_isbn13_too_short(self):
        assert is_isbn13("978896133483") is False

    def test_isbn10_valid(self):
        assert is_isbn10("8961334835") is True

    def test_isbn10_with_x(self):
        assert is_isbn10("080442957X") is True

    def test_isbn10_too_long(self):
        assert is_isbn10("9788961334839") is False


class TestISBN10to13:
    def test_standard_conversion(self):
        # 한국 ISBN-10 → ISBN-13
        result = isbn10_to_isbn13("8961334835")
        assert result.startswith("978")
        assert len(result) == 13

    def test_with_hyphens_stripped(self):
        result = isbn10_to_isbn13("89-613-3483-5")
        assert len(result) == 13


class TestNormalizeISBN:
    def test_isbn13_passthrough(self):
        assert normalize_isbn("9788961334839") == "9788961334839"

    def test_isbn13_with_hyphens(self):
        assert normalize_isbn("978-89-61-334839") == "9788961334839"

    def test_isbn10_converts_to_13(self):
        result = normalize_isbn("8961334835")
        assert len(result) == 13
        assert result.startswith("978")

    def test_empty_returns_empty(self):
        assert normalize_isbn("") == ""

    def test_already_13_digits(self):
        isbn = "9791165261696"
        assert normalize_isbn(isbn) == isbn


class TestISBNsEqual:
    def test_same_isbn13(self):
        assert isbns_equal("9788961334839", "9788961334839") is True

    def test_isbn10_vs_isbn13(self):
        # ISBN-10과 그에 해당하는 ISBN-13은 동일해야 함
        isbn13 = isbn10_to_isbn13("8961334835")
        assert isbns_equal("8961334835", isbn13) is True

    def test_different_isbns(self):
        assert isbns_equal("9788961334839", "9791165261696") is False

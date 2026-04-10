"""한국어 텍스트 유사도 테스트"""
import pytest
from bookips.utils.text import (
    normalize_title,
    normalize_author,
    title_similarity,
    author_similarity,
    combined_score,
)


class TestNormalizeTitle:
    def test_removes_year_in_parens(self):
        # (2023) 연도 표기 제거
        result = normalize_title("파이썬 입문(2023)")
        assert "2023" not in result

    def test_removes_edition_info(self):
        # 개정판 표기 제거
        result = normalize_title("개념원리 수학 (개정판)")
        assert "개정판" not in result

    def test_removes_grade_info(self):
        result = normalize_title("공통수학1(2025년 고1 적용)")
        assert "고1" not in result
        assert "2025" not in result

    def test_nfc_normalization(self):
        # 유니코드 정규화 (한글 분리 조합)
        nfc = normalize_title("한국어")
        assert isinstance(nfc, str)

    def test_empty_string(self):
        assert normalize_title("") == ""

    def test_removes_punctuation(self):
        result = normalize_title("Grammar Inside: Level 1")
        assert ":" not in result


class TestNormalizeAuthor:
    def test_removes_author_suffix(self):
        result = normalize_author("홍길동 저")
        assert "저" not in result

    def test_extracts_first_author(self):
        result = normalize_author("홍길동, 김철수, 이영희")
        assert "김철수" not in result

    def test_removes_et_al(self):
        result = normalize_author("홍길동 외 3명")
        assert "외" not in result

    def test_empty_string(self):
        assert normalize_author("") == ""


class TestTitleSimilarity:
    def test_identical_titles(self):
        assert title_similarity("파이썬 입문", "파이썬 입문") == 1.0

    def test_different_titles(self):
        score = title_similarity("파이썬 입문", "자바 프로그래밍")
        assert score < 0.5

    def test_edition_difference_high_similarity(self):
        # 개정판 차이는 제거 후 유사도가 높아야 함
        a = "개념원리 고등 공통수학1(2024년 고1 적용)"
        b = "개념원리 고등 공통수학1(2025년 고1 적용)"
        score = title_similarity(a, b)
        assert score > 0.85, f"유사도 {score:.3f}가 너무 낮음"

    def test_empty_title(self):
        assert title_similarity("", "파이썬 입문") == 0.0


class TestCombinedScore:
    def test_with_matching_title_and_author(self):
        score = combined_score(
            "파이썬 입문", "파이썬 입문",
            "홍길동", "홍길동"
        )
        assert score == pytest.approx(1.0)

    def test_title_only_when_no_author(self):
        # 저자 정보 없으면 도서명만으로 판단
        score = combined_score("파이썬 입문", "파이썬 입문", "", "")
        assert score == 1.0

    def test_threshold_check(self):
        # 70% 이상이면 매칭으로 간주
        score = combined_score(
            "개념원리 수학(개정)", "개념원리 수학",
            "홍성대", "홍성대"
        )
        assert score > 0.70

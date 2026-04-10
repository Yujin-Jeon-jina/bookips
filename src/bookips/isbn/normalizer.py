"""ISBN 정규화: ISBN-10/13 변환, 하이픈 제거, 체크섬 검증"""
from __future__ import annotations

import re


def strip_isbn(isbn: str) -> str:
    """ISBN에서 하이픈, 공백 제거"""
    return re.sub(r"[\s\-]", "", isbn.strip())


def is_isbn10(isbn: str) -> bool:
    """ISBN-10 형식 여부 (10자리, 마지막 자리 숫자 또는 X)"""
    s = strip_isbn(isbn)
    return len(s) == 10 and re.match(r"^\d{9}[\dX]$", s, re.IGNORECASE) is not None


def is_isbn13(isbn: str) -> bool:
    """ISBN-13 형식 여부 (13자리 숫자)"""
    s = strip_isbn(isbn)
    return len(s) == 13 and s.isdigit()


def _isbn10_checksum(digits: str) -> bool:
    """ISBN-10 체크섬 검증"""
    s = strip_isbn(digits).upper()
    if len(s) != 10:
        return False
    total = sum(
        (10 - i) * (10 if c == "X" else int(c))
        for i, c in enumerate(s)
    )
    return total % 11 == 0


def _isbn13_checksum(digits: str) -> bool:
    """ISBN-13 체크섬 검증"""
    s = strip_isbn(digits)
    if len(s) != 13 or not s.isdigit():
        return False
    weights = [1, 3] * 6
    total = sum(int(c) * w for c, w in zip(s[:12], weights))
    check = (10 - (total % 10)) % 10
    return check == int(s[12])


def isbn10_to_isbn13(isbn10: str) -> str:
    """ISBN-10 → ISBN-13 변환"""
    s = strip_isbn(isbn10).upper()
    if len(s) != 10:
        raise ValueError(f"유효한 ISBN-10이 아닙니다: {isbn10}")
    base = "978" + s[:9]
    weights = [1, 3] * 6
    total = sum(int(c) * w for c, w in zip(base, weights))
    check = (10 - (total % 10)) % 10
    return base + str(check)


def normalize_isbn(isbn: str) -> str:
    """
    ISBN을 13자리 형식으로 정규화.
    - 하이픈/공백 제거
    - ISBN-10이면 ISBN-13으로 변환
    - 유효하지 않으면 원본 반환 (로그 경고)

    Returns:
        정규화된 ISBN-13 문자열
    """
    if not isbn:
        return ""
    s = strip_isbn(isbn)

    if is_isbn13(s):
        return s

    if is_isbn10(s):
        return isbn10_to_isbn13(s)

    # 숫자만 남겨서 재시도 (잘못된 특수문자 포함 시)
    digits_only = re.sub(r"[^\dX]", "", s.upper())
    if len(digits_only) == 13 and digits_only.isdigit():
        return digits_only
    if len(digits_only) == 10:
        try:
            return isbn10_to_isbn13(digits_only)
        except ValueError:
            pass

    return s  # 변환 불가 시 원본 반환


def isbns_equal(a: str, b: str) -> bool:
    """두 ISBN이 동일한지 정규화 후 비교"""
    return normalize_isbn(a) == normalize_isbn(b)

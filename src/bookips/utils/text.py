"""한국어 텍스트 정규화 및 유사도 비교 유틸리티"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


# 판수/개정 표기 패턴 (도서명에서 제거)
_EDITION_PATTERNS = [
    r'\(.*?판.*?\)',        # (개정판), (3판), (제3개정판)
    r'\(.*?개정.*?\)',      # (개정), (2022개정)
    r'\[.*?판.*?\]',        # [개정판]
    r'제\s*\d+\s*판',       # 제3판, 제 3 판
    r'\d+\s*판',            # 3판
    r'개정\s*\d*\s*판',     # 개정판, 개정3판
    r'증보\s*판',           # 증보판
    r'전면\s*개정',         # 전면개정
    r'\(\d{4}\)',           # (2023), (2024) 연도 표기
    r'\(\d{4}년.*?\)',      # (2024년 고1 적용) 등
    r'[\(\[]\s*고\s*\d+\s*적용\s*[\)\]]',   # (고1 적용)
    r'[\(\[]\s*중\s*\d+\s*적용\s*[\)\]]',   # (중1 적용)
    r'[\(\[]\s*\d{4}\s*수능\s*대비\s*[\)\]]',  # (2026 수능대비)
]

_COMPILED_PATTERNS = [re.compile(p) for p in _EDITION_PATTERNS]

# 제거할 특수문자 패턴 (비교 시)
_PUNCT_RE = re.compile(r'[\s\-_·:：,，.。!！?？\(\)\[\]《》「」『』【】]')


def normalize_title(title: str) -> str:
    """
    도서명을 비교용으로 정규화.
    - 유니코드 NFC 정규화
    - 판수/개정 표기 제거
    - 특수문자·공백 제거
    - 소문자 변환
    """
    if not title:
        return ""

    text = unicodedata.normalize("NFC", title)

    for pat in _COMPILED_PATTERNS:
        text = pat.sub("", text)

    text = _PUNCT_RE.sub("", text)
    text = text.lower().strip()
    return text


def normalize_author(author: str) -> str:
    """
    저자명을 비교용으로 정규화.
    - '저', '저자', '지음', '글' 등 제거
    - '외', '공저' 등 제거하고 첫 저자만 추출
    """
    if not author:
        return ""

    text = unicodedata.normalize("NFC", author)

    # '외 X명', '공저' 등 제거
    text = re.sub(r'\s*(외\s*\d*\s*명?|공저|저자|지음|글|그림|저|역)\s*', "", text)
    # 쉼표나 '·'로 구분된 여러 저자 → 첫 저자만
    text = re.split(r'[,，·]', text)[0]
    text = _PUNCT_RE.sub("", text).lower().strip()
    return text


def title_similarity(a: str, b: str) -> float:
    """정규화된 두 도서명의 유사도 (0.0 ~ 1.0)"""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def author_similarity(a: str, b: str) -> float:
    """정규화된 두 저자명의 유사도 (0.0 ~ 1.0)"""
    na, nb = normalize_author(a), normalize_author(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def combined_score(
    title_a: str,
    title_b: str,
    author_a: str = "",
    author_b: str = "",
    title_weight: float = 0.7,
    author_weight: float = 0.3,
) -> float:
    """도서명과 저자명을 가중 합산한 최종 유사도 점수"""
    t_sim = title_similarity(title_a, title_b)
    if not author_a or not author_b:
        return t_sim
    a_sim = author_similarity(author_a, author_b)
    return title_weight * t_sim + author_weight * a_sim

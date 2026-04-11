"""한국어 텍스트 정규화 및 유사도 비교 유틸리티"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


# 판수/개정/연도 표기만 제거 (과목명·회수 등 핵심 구분자는 보존)
_EDITION_PATTERNS = [
    r'\(.*?판.*?\)',        # (개정판), (3판), (제3개정판)
    r'\(.*?개정.*?\)',      # (개정), (2022개정)
    r'\[.*?판.*?\]',        # [개정판]
    r'제\s*\d+\s*판',       # 제3판, 제 3 판
    r'개정\s*\d*\s*판',     # 개정판, 개정3판
    r'증보\s*판',           # 증보판
    r'전면\s*개정',         # 전면개정
    r'\(\d{4}\)',           # (2023), (2024) 연도 표기
    r'\(\d{4}년.*?\)',      # (2024년 고1 적용) 등
    r'[\(\[]\s*\d{4}\s*수능\s*대비\s*[\)\]]',  # (2026 수능대비)
    r'^\d{4}\s+',           # 앞쪽 연도: "2025 마더텅..." → "마더텅..."
]
# 주의: 과목명(영어, 국어, 수학 등), 회수(21회, 28회), 레벨(Level 1) 등은
# 다른 책을 구분하는 핵심 정보이므로 절대 제거하지 않음

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


# ─── 과목 키워드 추출 ───────────────────────────────────────

_SUBJECT_KEYWORDS = [
    "국어", "수학", "영어", "사회", "과학", "역사", "도덕", "윤리",
    "물리", "화학", "생물", "생명", "지구과학", "지학",
    "한국사", "세계사", "경제", "정치", "법", "지리",
    "화법", "작문", "독서", "문학", "언어", "매체",
    "미적분", "기하", "확률", "통계", "대수", "공통수학",
    "Grammar", "Reading", "Listening", "Voca", "VOCA",
]


def extract_subject(title: str) -> str:
    """도서명에서 과목 키워드 추출. 없으면 빈 문자열."""
    if not title:
        return ""
    for kw in _SUBJECT_KEYWORDS:
        if kw in title:
            return kw
    return ""


def same_subject(title_a: str, title_b: str) -> bool:
    """두 도서명의 과목이 같은지 비교. 둘 다 과목이 없으면 True."""
    subj_a = extract_subject(title_a)
    subj_b = extract_subject(title_b)
    if not subj_a or not subj_b:
        return True
    return subj_a == subj_b


# ─── 핵심 속성 추출 (학년, 레벨, 권수 등) ───────────────────

def extract_attributes(title: str) -> dict:
    """도서명에서 학년/레벨/권수 등 핵심 구분 속성 추출.

    이 속성이 다르면 아무리 제목이 비슷해도 다른 책.
    """
    if not title:
        return {}

    attrs = {}

    # 학년: 1학년~6학년, 중1~중3, 고1~고3
    m = re.search(r'(\d)\s*학년', title)
    if m:
        attrs["grade"] = m.group(1)

    m = re.search(r'[중고]\s*(\d)', title)
    if m:
        attrs["school_grade"] = m.group(0).replace(" ", "")

    # 레벨: Level 1, Level 2, L1, L2
    m = re.search(r'[Ll]evel\s*(\d)', title)
    if m:
        attrs["level"] = m.group(1)
    else:
        m = re.search(r'\bL(\d)\b', title)
        if m:
            attrs["level"] = m.group(1)

    # 권수/회수: 1권, 2권, 21회, 28회
    m = re.search(r'(\d+)\s*[권회]', title)
    if m:
        attrs["volume"] = m.group(1)

    # 상/하
    if re.search(r'[(\s]상[)\s]|상권', title):
        attrs["part"] = "상"
    elif re.search(r'[(\s]하[)\s]|하권', title):
        attrs["part"] = "하"

    # 학기: 1학기, 2학기
    m = re.search(r'(\d)\s*학기', title)
    if m:
        attrs["semester"] = m.group(1)

    return attrs


def attributes_compatible(title_a: str, title_b: str) -> bool:
    """두 도서의 핵심 속성이 호환되는지 확인.

    - 둘 다 있는데 값이 다르면 → False (다른 책)
    - 한쪽에만 학년/레벨이 있으면 → False (불확실 → 안전하게 차단)
    - 둘 다 없으면 → True
    """
    attrs_a = extract_attributes(title_a)
    attrs_b = extract_attributes(title_b)

    # 핵심 속성: 한쪽에만 있어도 차단해야 하는 것들
    critical_keys = {"grade", "school_grade", "level", "volume", "semester"}

    for key in set(attrs_a.keys()) | set(attrs_b.keys()):
        val_a = attrs_a.get(key)
        val_b = attrs_b.get(key)

        if val_a is not None and val_b is not None:
            # 둘 다 있는데 다르면 → 다른 책
            if val_a != val_b:
                return False
        elif key in critical_keys:
            # 핵심 속성이 한쪽에만 있으면 → 불확실 → 차단
            if val_a is not None or val_b is not None:
                return False

    return True

"""설정 로더: config/settings.yaml + .env 파일"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 프로젝트 루트 디렉토리 (config/settings.yaml이 있는 곳)
def _find_root() -> Path:
    # 1. 소스에서 직접 실행 시
    candidate = Path(__file__).parent.parent.parent
    if (candidate / "config" / "settings.yaml").exists():
        return candidate
    # 2. Buildpacks (/workspace) 또는 Docker (/app)
    for p in [Path("/workspace"), Path("/app"), Path.cwd()]:
        if (p / "config" / "settings.yaml").exists():
            return p
    return candidate

ROOT_DIR = _find_root()


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class ColumnMap:
    isbn: int
    publisher: int
    title: int
    unit_price: int
    start_date: int
    end_date: int


@dataclass
class UsageColumnMap:
    publisher: int
    isbn: int
    book_name: int
    usage_count: int
    unit_price: int
    amount: int
    authorized: int


@dataclass
class SettlementDetailColumns:
    period: int
    publisher: int
    isbn: int
    title: int
    usage_count: int
    unit_price: int
    amount: int


@dataclass
class ContractSheetConfig:
    spreadsheet_id: str
    worksheet: str
    header_rows: int
    columns: ColumnMap


@dataclass
class UsageSheetConfig:
    spreadsheet_id: str
    worksheet: str
    data_start_row: int
    columns: UsageColumnMap


@dataclass
class SettlementSheetConfig:
    spreadsheet_id: str
    summary_worksheet: str
    evidence_row_label: str
    individual_file_name_pattern: str
    settlement_detail_columns: SettlementDetailColumns


@dataclass
class NLApiConfig:
    base_url: str
    result_style: str
    page_size: int
    rate_limit_delay: float


@dataclass
class MatchingConfig:
    title_threshold: float
    author_threshold: float
    combined_threshold: float
    same_publisher_bonus: float


@dataclass
class Settings:
    contract: ContractSheetConfig
    usage: UsageSheetConfig
    settlement: SettlementSheetConfig
    nl_api: NLApiConfig
    matching: MatchingConfig
    database_path: Path

    # 환경 변수 기반 (시크릿)
    nl_api_key: str = field(default="")
    google_client_id: str = field(default="")
    google_client_secret: str = field(default="")
    google_redirect_uri: str = field(default="http://localhost:8000/auth/callback")
    secret_key: str = field(default="change-me")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = _load_settings()
    return _settings


def _load_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env")

    yaml_path = ROOT_DIR / "config" / "settings.yaml"
    raw = _load_yaml(yaml_path)

    sheets = raw.get("sheets", {})
    contract_raw = sheets.get("contract", {})
    usage_raw = sheets.get("usage", {})
    settlement_raw = sheets.get("settlement", {})

    nl_raw = raw.get("nl_api", {})
    matching_raw = raw.get("matching", {})
    db_raw = raw.get("database", {})

    contract_cols = contract_raw.get("columns", {})
    usage_cols = usage_raw.get("columns", {})
    settlement_cols = settlement_raw.get("settlement_detail_columns", {})

    return Settings(
        contract=ContractSheetConfig(
            spreadsheet_id=contract_raw["spreadsheet_id"],
            worksheet=contract_raw["worksheet"],
            header_rows=contract_raw.get("header_rows", 2),
            columns=ColumnMap(
                isbn=contract_cols["isbn"],
                publisher=contract_cols["publisher"],
                title=contract_cols["title"],
                unit_price=contract_cols["unit_price"],
                start_date=contract_cols["start_date"],
                end_date=contract_cols["end_date"],
            ),
        ),
        usage=UsageSheetConfig(
            spreadsheet_id=usage_raw["spreadsheet_id"],
            worksheet=usage_raw["worksheet"],
            data_start_row=usage_raw.get("data_start_row", 8),
            columns=UsageColumnMap(
                publisher=usage_cols["publisher"],
                isbn=usage_cols["isbn"],
                book_name=usage_cols["book_name"],
                usage_count=usage_cols["usage_count"],
                unit_price=usage_cols["unit_price"],
                amount=usage_cols["amount"],
                authorized=usage_cols["authorized"],
            ),
        ),
        settlement=SettlementSheetConfig(
            spreadsheet_id=settlement_raw["spreadsheet_id"],
            summary_worksheet=settlement_raw["summary_worksheet"],
            evidence_row_label=settlement_raw.get("evidence_row_label", "증빙(정산내역)"),
            individual_file_name_pattern=settlement_raw["individual_file_name_pattern"],
            settlement_detail_columns=SettlementDetailColumns(
                period=settlement_cols["period"],
                publisher=settlement_cols["publisher"],
                isbn=settlement_cols["isbn"],
                title=settlement_cols["title"],
                usage_count=settlement_cols["usage_count"],
                unit_price=settlement_cols["unit_price"],
                amount=settlement_cols["amount"],
            ),
        ),
        nl_api=NLApiConfig(
            base_url=nl_raw.get("base_url", "https://www.nl.go.kr/seoji/SearchApi.do"),
            result_style=nl_raw.get("result_style", "json"),
            page_size=nl_raw.get("page_size", 10),
            rate_limit_delay=nl_raw.get("rate_limit_delay", 0.5),
        ),
        matching=MatchingConfig(
            title_threshold=matching_raw.get("title_threshold", 0.75),
            author_threshold=matching_raw.get("author_threshold", 0.65),
            combined_threshold=matching_raw.get("combined_threshold", 0.70),
            same_publisher_bonus=matching_raw.get("same_publisher_bonus", 0.05),
        ),
        database_path=ROOT_DIR / db_raw.get("path", "data/bookips.db"),
        nl_api_key=os.getenv("NL_API_KEY", ""),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback"),
        secret_key=os.getenv("SECRET_KEY", "change-me"),
    )

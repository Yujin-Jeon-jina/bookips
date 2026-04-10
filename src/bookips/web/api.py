"""HTMX용 API 엔드포인트

HTMX에서 호출하여 부분 HTML 조각을 반환하거나 JSON 응답.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bookips.config import ROOT_DIR

router = APIRouter(prefix="/api", tags=["api"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
logger = logging.getLogger(__name__)


@router.get("/publishers", response_class=HTMLResponse)
async def get_publishers(request: Request):
    """출판사 목록 조회 → select option HTML"""
    from bookips.sheets.contract import get_publisher_list
    try:
        publishers = get_publisher_list()
    except Exception as e:
        logger.error("출판사 목록 조회 실패: %s", e)
        return HTMLResponse(f'<option value="">오류: {e}</option>')

    options = ['<option value="">출판사 선택</option>']
    options += [f'<option value="{p}">{p}</option>' for p in publishers]
    return HTMLResponse("\n".join(options))


@router.post("/settlement/preview", response_class=HTMLResponse)
async def settlement_preview(
    request: Request,
    publisher: str = Form(...),
):
    """정산 미리보기 (시트 쓰기 없이 매칭 결과만)"""
    from bookips.settlement.engine import SettlementEngine

    try:
        engine = SettlementEngine()
        result = engine.preview_settlement(publisher)
    except Exception as e:
        logger.error("정산 미리보기 실패: %s", e)
        return templates.TemplateResponse(
            "components/error.html",
            {"request": request, "error": str(e)},
        )

    return templates.TemplateResponse(
        "components/settlement_result.html",
        {"request": request, "result": result},
    )


@router.post("/settlement/execute", response_class=HTMLResponse)
async def settlement_execute(
    request: Request,
    publisher: str = Form(...),
    year: int = Form(...),
    month: int = Form(...),
):
    """정산 실행 (시트에 실제 쓰기)"""
    from bookips.settlement.engine import SettlementEngine

    try:
        engine = SettlementEngine()
        result = engine.run_settlement(publisher, year, month, dry_run=False)
    except Exception as e:
        logger.error("정산 실행 실패: %s", e)
        return templates.TemplateResponse(
            "components/error.html",
            {"request": request, "error": str(e)},
        )

    return templates.TemplateResponse(
        "components/settlement_result.html",
        {"request": request, "result": result, "executed": True},
    )


@router.post("/mapping/add", response_class=HTMLResponse)
async def add_mapping(
    request: Request,
    usage_isbn: str = Form(...),
    contract_isbn: str = Form(...),
):
    """수동 ISBN 매핑 추가"""
    from bookips.isbn.cache import ISBNCache
    from bookips.isbn.normalizer import normalize_isbn

    cache = ISBNCache()
    cache.save_mapping(
        normalize_isbn(usage_isbn),
        normalize_isbn(contract_isbn),
        "manual",
        1.0,
    )

    mappings = cache.list_mappings()
    return templates.TemplateResponse(
        "components/mapping_table.html",
        {"request": request, "mappings": mappings},
    )


@router.post("/mapping/delete", response_class=HTMLResponse)
async def delete_mapping(
    request: Request,
    usage_isbn: str = Form(...),
):
    """ISBN 매핑 삭제"""
    from bookips.isbn.cache import ISBNCache

    cache = ISBNCache()
    cache.delete_mapping(usage_isbn)

    mappings = cache.list_mappings()
    return templates.TemplateResponse(
        "components/mapping_table.html",
        {"request": request, "mappings": mappings},
    )


@router.get("/isbn/search", response_class=HTMLResponse)
async def isbn_search(
    request: Request,
    isbn: str = Query(...),
):
    """국립중앙도서관 API로 ISBN 조회"""
    from bookips.isbn.nl_api import NLApiClient
    from bookips.isbn.normalizer import normalize_isbn

    client = NLApiClient()
    norm = normalize_isbn(isbn)
    metadata = client.lookup_isbn(norm)

    return templates.TemplateResponse(
        "components/isbn_result.html",
        {"request": request, "isbn": norm, "metadata": metadata},
    )

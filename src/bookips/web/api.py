"""HTMX용 API 엔드포인트"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bookips.config import ROOT_DIR

router = APIRouter(prefix="/api", tags=["api"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
logger = logging.getLogger(__name__)


def _render(request: Request, name: str, **kwargs):
    """Starlette 호환 TemplateResponse: request를 첫 인자로"""
    return templates.TemplateResponse(request, name, kwargs)


@router.get("/publishers", response_class=HTMLResponse)
async def get_publishers(request: Request):
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
    year: int = Form(2026),
    month: int = Form(1),
    prev_file_url: str = Form(""),
):
    from bookips.settlement.engine import SettlementEngine
    try:
        engine = SettlementEngine()
        result = engine.run_settlement(publisher, year, month, dry_run=True)
        result.prev_file_url = prev_file_url  # 템플릿에서 시트저장 시 전달
    except Exception as e:
        logger.error("정산 미리보기 실패: %s", e)
        return _render(request, "components/error.html", error=str(e))

    return _render(request, "components/settlement_result.html", result=result)


@router.post("/settlement/execute", response_class=HTMLResponse)
async def settlement_execute(
    request: Request,
    publisher: str = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    prev_file_url: str = Form(""),
):
    from bookips.settlement.engine import SettlementEngine
    try:
        engine = SettlementEngine()
        result = engine.run_settlement(publisher, year, month, dry_run=False, prev_file_url=prev_file_url)
    except Exception as e:
        logger.error("정산 실행 실패: %s", e)
        return _render(request, "components/error.html", error=str(e))

    return _render(request, "components/settlement_result.html", result=result, executed=True)


@router.post("/mapping/add", response_class=HTMLResponse)
async def add_mapping(
    request: Request,
    usage_isbn: str = Form(...),
    contract_isbn: str = Form(...),
):
    from bookips.isbn.cache import ISBNCache
    from bookips.isbn.normalizer import normalize_isbn

    cache = ISBNCache()
    cache.save_mapping(normalize_isbn(usage_isbn), normalize_isbn(contract_isbn), "manual", 1.0)
    mappings = cache.list_mappings()
    return _render(request, "components/mapping_table.html", mappings=mappings)


@router.post("/mapping/delete", response_class=HTMLResponse)
async def delete_mapping(
    request: Request,
    usage_isbn: str = Form(...),
):
    from bookips.isbn.cache import ISBNCache

    cache = ISBNCache()
    cache.delete_mapping(usage_isbn)
    mappings = cache.list_mappings()
    return _render(request, "components/mapping_table.html", mappings=mappings)


@router.get("/isbn/search", response_class=HTMLResponse)
async def isbn_search(
    request: Request,
    isbn: str = Query(...),
):
    from bookips.isbn.nl_api import NLApiClient
    from bookips.isbn.normalizer import normalize_isbn

    client = NLApiClient()
    norm = normalize_isbn(isbn)
    metadata = client.lookup_isbn(norm)
    return _render(request, "components/isbn_result.html", isbn=norm, metadata=metadata)

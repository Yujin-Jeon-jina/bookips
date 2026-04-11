"""웹 페이지 라우트 (Jinja2 HTML 렌더링)"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bookips.config import ROOT_DIR
from bookips.sheets.client import get_google_client

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


def _render(request: Request, name: str, **kwargs):
    """Starlette 호환 TemplateResponse: request를 첫 인자로"""
    client = get_google_client()
    ctx = {"authenticated": client.is_authenticated, **kwargs}
    return templates.TemplateResponse(request, name, ctx)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _render(request, "dashboard.html")


@router.get("/settlement", response_class=HTMLResponse)
async def settlement_page(request: Request):
    return _render(request, "settlement.html")


@router.get("/mapping", response_class=HTMLResponse)
@router.post("/mapping", response_class=HTMLResponse)
async def mapping_page(request: Request):
    from bookips.isbn.cache import ISBNCache
    from bookips.isbn.normalizer import normalize_isbn
    cache = ISBNCache()
    mappings = cache.list_mappings()

    # 계약 ISBN 목록 로드하여 검증용 세트 생성
    contract_isbns = set()
    try:
        from bookips.sheets.contract import read_contract_books
        books = read_contract_books(active_only=True)
        contract_isbns = {b.isbn for b in books}
    except Exception:
        pass

    for m in mappings:
        m["contract_exists"] = normalize_isbn(m["contract_isbn"]) in contract_isbns

    # POST: 정산 결과에서 미매칭 항목이 넘어옴
    prefill = []
    if request.method == "POST":
        form = await request.form()
        unmatched_isbns = form.getlist("unmatched_isbns")
        unmatched_names = form.getlist("unmatched_names")
        candidate_isbns = form.getlist("candidate_isbns")
        for i, isbn in enumerate(unmatched_isbns):
            prefill.append({
                "usage_isbn": isbn,
                "book_name": unmatched_names[i] if i < len(unmatched_names) else "",
                "candidate_isbn": candidate_isbns[i] if i < len(candidate_isbns) else "",
            })

    return _render(request, "mapping.html", mappings=mappings, prefill=prefill)


@router.get("/isbn/lookup", response_class=HTMLResponse)
async def isbn_lookup_page(request: Request):
    return _render(request, "isbn_lookup.html")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    from bookips.config import get_settings
    s = get_settings()
    settings_data = {
        "contract_id": s.contract.spreadsheet_id,
        "usage_id": s.usage.spreadsheet_id,
        "settlement_id": s.settlement.spreadsheet_id,
        "title_threshold": s.matching.title_threshold,
        "combined_threshold": s.matching.combined_threshold,
        "same_publisher_bonus": s.matching.same_publisher_bonus,
        "nl_api_key": s.nl_api_key,
        "google_client_id": s.google_client_id,
    }
    return _render(request, "settings.html", settings=settings_data)

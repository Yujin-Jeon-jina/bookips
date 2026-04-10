"""웹 페이지 라우트 (Jinja2 HTML 렌더링)"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bookips.config import ROOT_DIR
from bookips.sheets.client import get_google_client

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


def _ctx(request: Request, **kwargs) -> dict:
    """템플릿 공통 컨텍스트"""
    client = get_google_client()
    return {"request": request, "authenticated": client.is_authenticated, **kwargs}


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", _ctx(request))


@router.get("/settlement", response_class=HTMLResponse)
async def settlement_page(request: Request):
    return templates.TemplateResponse("settlement.html", _ctx(request))


@router.get("/mapping", response_class=HTMLResponse)
async def mapping_page(request: Request):
    from bookips.isbn.cache import ISBNCache
    cache = ISBNCache()
    mappings = cache.list_mappings()
    return templates.TemplateResponse("mapping.html", _ctx(request, mappings=mappings))


@router.get("/isbn/lookup", response_class=HTMLResponse)
async def isbn_lookup_page(request: Request):
    return templates.TemplateResponse("isbn_lookup.html", _ctx(request))

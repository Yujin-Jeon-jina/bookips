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
    """템플릿 공통 컨텍스트 (request 제외)"""
    client = get_google_client()
    return {"authenticated": client.is_authenticated, **kwargs}


def _render(request: Request, name: str, **kwargs):
    """Starlette 버전 호환 TemplateResponse"""
    ctx = _ctx(request, **kwargs)
    ctx["request"] = request
    return templates.TemplateResponse(name, ctx)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _render(request, "dashboard.html")


@router.get("/settlement", response_class=HTMLResponse)
async def settlement_page(request: Request):
    return _render(request, "settlement.html")


@router.get("/mapping", response_class=HTMLResponse)
async def mapping_page(request: Request):
    from bookips.isbn.cache import ISBNCache
    cache = ISBNCache()
    mappings = cache.list_mappings()
    return _render(request, "mapping.html", mappings=mappings)


@router.get("/isbn/lookup", response_class=HTMLResponse)
async def isbn_lookup_page(request: Request):
    return _render(request, "isbn_lookup.html")

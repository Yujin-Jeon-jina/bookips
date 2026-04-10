"""BookIPS FastAPI 앱 진입점"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bookips.config import ROOT_DIR
from bookips.web.auth import router as auth_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="BookIPS",
    description="도서 IP 정산 자동화 시스템",
    version="0.1.0",
)

# 정적 파일
static_dir = ROOT_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Jinja2 템플릿
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

# 라우터 등록
app.include_router(auth_router)


@app.get("/health")
async def health():
    """헬스 체크"""
    return {"status": "ok", "version": "0.1.0"}


# 메인 페이지 (임시 - Phase 5에서 완성)
from fastapi import Request
from fastapi.responses import HTMLResponse


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    from bookips.sheets.client import get_google_client
    client = get_google_client()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "authenticated": client.is_authenticated,
        },
    )

"""BookIPS FastAPI 앱 진입점"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bookips.config import ROOT_DIR
from bookips.web.auth import router as auth_router
from bookips.web.routes import router as pages_router
from bookips.web.api import router as api_router

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

# 라우터 등록
app.include_router(auth_router)
app.include_router(pages_router)
app.include_router(api_router)


@app.get("/health")
async def health():
    """헬스 체크"""
    return {"status": "ok", "version": "0.1.0"}

"""Google OAuth2 인증 웹 라우트

플로우:
  GET  /auth/login    → Google 인증 페이지로 리다이렉트
  GET  /auth/callback → 인증 코드 수신 → 토큰 저장 → 대시보드로 리다이렉트
  POST /auth/logout   → 토큰 삭제
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from bookips.sheets.client import TOKEN_PATH, get_google_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login():
    """Google OAuth2 로그인 페이지로 리다이렉트"""
    client = get_google_client()
    auth_url = client.get_auth_url()
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def callback(request: Request):
    """Google OAuth2 콜백 처리"""
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        logger.warning("OAuth 인증 오류: %s", error)
        return RedirectResponse(url="/?error=auth_failed")

    if not code:
        return RedirectResponse(url="/?error=no_code")

    try:
        client = get_google_client()
        client.exchange_code(code)
        logger.info("Google 인증 성공")
    except Exception as e:
        logger.error("토큰 교환 실패: %s", e)
        return RedirectResponse(url="/?error=token_exchange_failed")

    return RedirectResponse(url="/")


@router.post("/logout")
async def logout():
    """토큰 삭제 (로그아웃)"""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        logger.info("토큰 삭제 완료 (로그아웃)")

    # 싱글턴 초기화
    import bookips.sheets.client as c
    c._client = None

    return RedirectResponse(url="/", status_code=303)


def require_auth(request: Request) -> bool:
    """현재 요청이 인증된 상태인지 확인"""
    client = get_google_client()
    return client.is_authenticated

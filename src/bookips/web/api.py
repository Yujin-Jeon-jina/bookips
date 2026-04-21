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


@router.post("/mapping/add-bulk", response_class=HTMLResponse)
async def add_mapping_bulk(request: Request):
    """여러 ISBN 매핑 일괄 추가"""
    from bookips.isbn.cache import ISBNCache
    from bookips.isbn.normalizer import normalize_isbn

    form = await request.form()
    usage_isbns = form.getlist("usage_isbns")
    contract_isbns = form.getlist("contract_isbns")

    cache = ISBNCache()
    count = 0
    for u, c in zip(usage_isbns, contract_isbns):
        u, c = u.strip(), c.strip()
        if u and c:
            cache.save_mapping(normalize_isbn(u), normalize_isbn(c), "manual", 1.0)
            count += 1

    logger.info("수동 매핑 %d건 일괄 추가", count)
    mappings = cache.list_mappings()
    return _render(request, "components/mapping_table.html", mappings=mappings)


@router.post("/mapping/auto-search", response_class=HTMLResponse)
async def auto_search_mapping(request: Request):
    """미매칭 ISBN의 다른 판본을 국립중앙도서관 API로 자동 검색"""
    from bookips.isbn.nl_api import NLApiClient
    from bookips.isbn.normalizer import normalize_isbn
    from bookips.sheets.contract import read_contract_books
    import time

    form = await request.form()
    usage_isbns = form.getlist("usage_isbns")

    # 계약 ISBN 목록 로드
    try:
        books = read_contract_books(active_only=True)
        contract_isbn_set = {b.isbn for b in books}
        contract_map = {b.isbn: b.title for b in books}
    except Exception as e:
        return _render(request, "components/error.html", error=f"계약 목록 로드 실패: {e}")

    api = NLApiClient()
    results = []  # [(usage_isbn, contract_isbn, usage_title, contract_title)]

    for isbn in usage_isbns:
        isbn = normalize_isbn(isbn.strip())
        if not isbn:
            continue

        matches = api.find_related_isbns(isbn, contract_isbn_set)
        if matches:
            for contract_isbn, title in matches:
                contract_title = contract_map.get(contract_isbn, title)
                results.append((isbn, contract_isbn, title, contract_title))
        else:
            # API에서 원본 정보라도 표시
            meta = api.lookup_isbn(isbn)
            results.append((isbn, "", meta.title if meta else "조회 실패", ""))

        time.sleep(0.5)

    return _render(request, "components/auto_search_result.html", results=results)


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




@router.post("/settings/matching", response_class=HTMLResponse)
async def save_matching_settings(
    request: Request,
    title_threshold: float = Form(...),
    combined_threshold: float = Form(...),
    same_publisher_bonus: float = Form(...),
):
    """매칭 임계값 변경 (런타임)"""
    from bookips.config import get_settings
    s = get_settings()
    s.matching.title_threshold = title_threshold
    s.matching.combined_threshold = combined_threshold
    s.matching.same_publisher_bonus = same_publisher_bonus
    logger.info("매칭 설정 변경: title=%.2f, combined=%.2f, bonus=%.2f", title_threshold, combined_threshold, same_publisher_bonus)
    return HTMLResponse('<div class="alert" style="background:#dcfce7;border:1px solid #86efac">매칭 설정 저장 완료</div>')

"""정산 시트 조작: 전월 파일 복사, 이름 변경, 데이터 입력, Link 업데이트

정산 메인 시트([판다과외] 미니멈개런티(MG)사용량 summary)에서
증빙(정산내역) Link를 읽고, 전월 파일을 복사하여 당월 정산 파일을 생성.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import gspread

from bookips.config import get_settings
from bookips.models import SettlementRow
from bookips.sheets.client import get_google_client

logger = logging.getLogger(__name__)


def _match_publisher(name: str, cell: str) -> bool:
    """출판사명 유연 매칭. 공백/대소문자 무시, 부분 일치."""
    if not name or not cell:
        return False
    # 공백 제거 후 비교
    n = name.replace(" ", "").lower()
    c = cell.replace(" ", "").lower()
    # 정확히 포함되거나, 핵심 키워드가 포함되면 매칭
    if n in c or c in n:
        return True
    # "NE능률" ↔ "능률" 등 부분 매칭
    # 한글 부분만 추출해서 비교
    import re
    korean_n = re.sub(r'[^가-힣]', '', name)
    korean_c = re.sub(r'[^가-힣]', '', cell)
    if korean_n and korean_c and (korean_n in korean_c or korean_c in korean_n):
        return True
    return False


def find_publisher_block(
    all_values: list[list[str]],
    publisher_name: str,
) -> Optional[dict]:
    """정산 메인 시트에서 특정 출판사 블록의 행 범위 탐색.

    출판사 블록은 A열에 출판사 번호+이름(e.g., '1 개념원리')이 있고,
    그 아래에 기초잔액, 충전, MG사용, ... 증빙(정산내역) 행이 있음.

    Returns:
        {'start_row': int, 'evidence_row': int, 'item_row': int} 또는 None
    """
    settings = get_settings()
    evidence_label = settings.settlement.evidence_row_label

    for i, row in enumerate(all_values):
        # A~C열에서 출판사명 검색 (유연한 매칭)
        for col_idx in range(min(3, len(row))):
            cell = row[col_idx].strip() if row else ""
            # 정확 포함, 공백 무시, 대소문자 무시
            if _match_publisher(publisher_name, cell):
                # 출판사 블록 시작 → 아래로 내려가며 각 행 레이블 찾기
                block = {"start_row": i}
                for j in range(i, min(i + 20, len(all_values))):
                    inner_row = all_values[j]
                    for cell2 in inner_row[:3]:
                        label = cell2.strip()
                        if evidence_label in label:
                            block["evidence_row"] = j
                        if "Item" in label or "item" in label.lower():
                            block["item_row"] = j
                        if "기말잔액" in label:
                            block["balance_row"] = j
                    if "기초잔액" in label:
                        block["opening_row"] = j
                    if "MG사용" in label and "추가" not in label:
                        block["mg_usage_row"] = j

            if "evidence_row" in block:
                block.setdefault("item_row", i + 1)
                return block
    return None


def get_mg_balance(
    all_values: list[list[str]],
    block: dict,
    month_col: int,
) -> Optional[int]:
    """출판사 블록에서 특정 월의 기말잔액 읽기"""
    balance_row = block.get("balance_row")
    if balance_row is None or month_col is None:
        return None
    row_data = all_values[balance_row]
    if month_col < len(row_data):
        return _parse_amount(row_data[month_col])
    return None


def _parse_amount(value: str) -> int:
    """금액 문자열 → int. '₩33,336,897' 또는 '-₩5,059,000' → 정수"""
    if not value or not value.strip():
        return 0
    cleaned = value.replace("₩", "").replace("\\", "").replace(",", "").replace("원", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def find_month_column(
    item_row_values: list[str],
    year: int,
    month: int,
) -> Optional[int]:
    """Item 행에서 해당 월의 컬럼 인덱스 찾기.

    Item 행은 날짜 헤더가 있음: '2026. 3. 1', '2026.3.1' 등
    """
    target_patterns = [
        f"{year}. {month}. 1",
        f"{year}.{month}.1",
        f"{year}. {month:02d}. 1",
        f"{year}.{month:02d}.1",
        f"{year}. {month}.",
        f"{year}-{month:02d}",
    ]

    for col_idx, cell in enumerate(item_row_values):
        cell_clean = cell.strip()
        for pattern in target_patterns:
            if pattern in cell_clean:
                return col_idx

    return None


def get_evidence_link(
    spreadsheet_id: str,
    worksheet_title: str,
    evidence_row: int,
    month_col: int,
) -> Optional[str]:
    """증빙(정산내역) 행의 특정 월 셀에서 하이퍼링크 URL 추출"""
    client = get_google_client()
    ws = client.get_worksheet(spreadsheet_id, worksheet_title)

    # gspread의 cell은 1-indexed
    cell = ws.cell(evidence_row + 1, month_col + 1)

    # 하이퍼링크가 걸려있으면 셀 값이 'Link'이고 실제 URL은 별도 추출 필요
    # gspread에서 하이퍼링크 URL 가져오기: HYPERLINK 수식 파싱
    cell_formula = None
    try:
        cell_formula = ws.acell(
            gspread.utils.rowcol_to_a1(evidence_row + 1, month_col + 1),
            value_render_option="FORMULA",
        ).value
    except Exception as e:
        logger.warning("수식 조회 실패: %s", e)

    if cell_formula and "HYPERLINK" in str(cell_formula).upper():
        # =HYPERLINK("url", "Link") 형식 파싱
        m = re.search(r'HYPERLINK\s*\(\s*"([^"]+)"', str(cell_formula))
        if m:
            return m.group(1)

    # 수식이 아니면 셀 값 자체가 URL일 수 있음
    if cell.value and cell.value.startswith("http"):
        return cell.value

    return None


def copy_settlement_file(
    source_file_id: str,
    publisher: str,
    year: int,
    month: int,
) -> str:
    """전월 정산 파일을 복사하여 당월 파일 생성.

    Args:
        source_file_id: 전월 정산 파일의 Google Drive 파일 ID
        publisher: 출판사명
        year: 연도 (e.g., 2026)
        month: 월 (e.g., 3)

    Returns:
        새로 생성된 파일의 ID
    """
    settings = get_settings()
    pattern = settings.settlement.individual_file_name_pattern
    yy = year % 100  # 26
    new_name = pattern.format(yy=yy, mm=month, publisher=publisher)

    client = get_google_client()
    new_file_id = client.copy_file(source_file_id, new_name)
    logger.info("정산 파일 복사 완료: %s (ID: %s)", new_name, new_file_id)
    return new_file_id


def write_settlement_data(
    file_id: str,
    rows: list[SettlementRow],
    prev_mg_balance: Optional[int] = None,
) -> None:
    """정산 파일의 첫 번째 탭에 정산 데이터 쓰기.

    기존 데이터를 지우고 새 데이터 + 합계 + MG 잔액 입력.
    """
    client = get_google_client()
    ss = client.open_spreadsheet(file_id)
    ws = ss.sheet1  # 첫 번째 탭

    # 기존 데이터 클리어 (헤더 포함 전체)
    existing = ws.get_all_values()
    if existing:
        last_row = max(len(existing), 1)
        last_col = max(len(existing[0]) if existing[0] else 7, 7)
        clear_range = f"A1:{gspread.utils.rowcol_to_a1(last_row, last_col)}"
        ws.batch_clear([clear_range])

    if not rows:
        logger.info("쓸 데이터 없음 (file_id: %s)", file_id)
        return

    # 헤더 행 쓰기
    headers = [""] * 7
    headers[0] = "정산 기간"
    headers[1] = "출판사"
    headers[2] = "isbn"
    headers[3] = "교재명"
    headers[4] = "등록 교재 수"
    headers[5] = "교재 정가"
    headers[6] = "정산 금액"
    ws.update("A1:G1", [headers])

    # 데이터 변환: SettlementRow → 2D 리스트
    settings = get_settings()
    cols = settings.settlement.settlement_detail_columns
    max_col = max(cols.period, cols.publisher, cols.isbn, cols.title,
                  cols.usage_count, cols.unit_price, cols.amount) + 1

    values = []
    for row in rows:
        line = [""] * max_col
        line[cols.period] = row.period
        line[cols.publisher] = row.publisher
        line[cols.isbn] = row.contract_isbn
        line[cols.title] = row.title
        line[cols.usage_count] = row.usage_count
        line[cols.unit_price] = row.unit_price
        line[cols.amount] = row.amount
        values.append(line)

    # 합계 행 추가
    total_count = sum(r.usage_count for r in rows)
    total_amount = sum(r.amount for r in rows)
    summary_line = [""] * max_col
    summary_line[cols.title] = "합계"
    summary_line[cols.usage_count] = total_count
    summary_line[cols.amount] = total_amount
    values.append([""] * max_col)  # 빈 행
    values.append(summary_line)

    # MG 잔액 정보 추가
    if prev_mg_balance is not None:
        values.append([""] * max_col)  # 빈 행
        mg_row1 = [""] * max_col
        mg_row1[cols.title] = "전월 MG 잔액"
        mg_row1[cols.amount] = prev_mg_balance
        values.append(mg_row1)

        mg_row2 = [""] * max_col
        mg_row2[cols.title] = f"당월 사용액"
        mg_row2[cols.amount] = -total_amount
        values.append(mg_row2)

        remaining = prev_mg_balance - total_amount
        mg_row3 = [""] * max_col
        mg_row3[cols.title] = "사용분 제외 잔여금액"
        mg_row3[cols.amount] = remaining
        values.append(mg_row3)

    # A2부터 쓰기
    end_col = gspread.utils.rowcol_to_a1(1, max_col).replace("1", "")
    write_range = f"A2:{end_col}{len(values) + 1}"
    ws.update(write_range, values)

    logger.info("정산 데이터 %d건 + 합계/MG잔액 입력 완료 (file_id: %s)", len(rows), file_id)


def update_evidence_link(
    spreadsheet_id: str,
    worksheet_title: str,
    evidence_row: int,
    month_col: int,
    new_file_id: str,
) -> None:
    """정산 메인 시트의 증빙(정산내역) 셀에 새 파일 링크 업데이트"""
    client = get_google_client()
    ws = client.get_worksheet(spreadsheet_id, worksheet_title)

    new_url = f"https://docs.google.com/spreadsheets/d/{new_file_id}/edit"
    cell_a1 = gspread.utils.rowcol_to_a1(evidence_row + 1, month_col + 1)

    # HYPERLINK 수식으로 입력
    formula = f'=HYPERLINK("{new_url}", "Link")'
    ws.update_acell(cell_a1, formula)

    logger.info("증빙 Link 업데이트: %s → %s", cell_a1, new_url)

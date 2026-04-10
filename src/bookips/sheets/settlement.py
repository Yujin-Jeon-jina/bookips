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
        # A열 또는 B열에서 출판사명 검색
        cell_a = row[0].strip() if row and len(row) > 0 else ""
        cell_b = row[1].strip() if row and len(row) > 1 else ""

        # "1 개념원리", "2 씨두" 등의 패턴
        if publisher_name in cell_a or publisher_name in cell_b:
            # 출판사 블록 시작 → 아래로 내려가며 증빙(정산내역) 행 찾기
            for j in range(i, min(i + 20, len(all_values))):
                inner_row = all_values[j]
                for cell in inner_row[:3]:  # A~C 열에서 레이블 탐색
                    if evidence_label in cell.strip():
                        # Item 행 (날짜 헤더) 찾기
                        item_row = None
                        for k in range(i, j):
                            for c in all_values[k][:3]:
                                if "Item" in c or "item" in c.lower():
                                    item_row = k
                                    break
                        return {
                            "start_row": i,
                            "evidence_row": j,
                            "item_row": item_row or i + 1,
                        }
    return None


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
) -> None:
    """정산 파일의 첫 번째 탭에 정산 데이터 쓰기.

    기존 데이터를 지우고 새 데이터를 입력.
    """
    client = get_google_client()
    ss = client.open_spreadsheet(file_id)
    ws = ss.sheet1  # 첫 번째 탭

    # 기존 데이터 범위 파악 (헤더 행 제외하고 2행부터)
    # 헤더(1행)는 유지, 2행부터 데이터 영역 초기화
    existing = ws.get_all_values()
    if len(existing) > 1:
        # 2행부터 마지막 행까지 클리어
        last_row = len(existing)
        last_col = len(existing[0]) if existing[0] else 7
        clear_range = f"A2:{gspread.utils.rowcol_to_a1(last_row, last_col)}"
        ws.batch_clear([clear_range])

    if not rows:
        logger.info("쓸 데이터 없음 (file_id: %s)", file_id)
        return

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

    # A2부터 쓰기
    end_col = gspread.utils.rowcol_to_a1(1, max_col).replace("1", "")
    write_range = f"A2:{end_col}{len(values) + 1}"
    ws.update(write_range, values)

    logger.info("정산 데이터 %d건 입력 완료 (file_id: %s)", len(values), file_id)


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

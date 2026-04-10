"""정산 결과 리포트 생성"""
from __future__ import annotations

from bookips.models import SettlementResult


def format_report(result: SettlementResult) -> str:
    """정산 결과를 텍스트 리포트로 변환"""
    lines = [
        f"=== 정산 리포트: {result.publisher} ({result.period}) ===",
        "",
        f"매칭 성공: {len(result.rows)}건",
        f"미매칭:    {len(result.unmatched)}건",
        f"매칭율:    {result.match_rate:.1%}",
        f"총 정산액: ₩{result.total_amount:,}",
        "",
    ]

    if result.rows:
        lines.append("── 정산 내역 ──")
        lines.append(f"{'ISBN':<16} {'교재명':<40} {'사용수':>6} {'단가':>10} {'정산액':>12} {'방법':<8}")
        lines.append("-" * 100)

        for row in result.rows:
            title_short = row.title[:38] + ".." if len(row.title) > 40 else row.title
            lines.append(
                f"{row.contract_isbn:<16} {title_short:<40} {row.usage_count:>6} "
                f"₩{row.unit_price:>8,} ₩{row.amount:>10,} {row.match_method:<8}"
            )
        lines.append("")

    if result.unmatched:
        lines.append("── 미매칭 (수동 검토 필요) ──")
        for um in result.unmatched:
            api_title = um.metadata.title if um.metadata else "API 조회 실패"
            lines.append(f"  ISBN: {um.usage_isbn}")
            lines.append(f"    시트 교재명: {um.book_name}")
            lines.append(f"    API 도서명:  {api_title}")
            lines.append(f"    사용수: {um.usage_count}, 단가: ₩{um.unit_price:,}")

            if um.candidates:
                lines.append("    후보:")
                for book, score in um.candidates:
                    lines.append(f"      [{score:.0%}] {book.isbn} {book.title}")
            lines.append("")

    if result.new_file_url:
        lines.append(f"정산 파일: {result.new_file_url}")

    return "\n".join(lines)


def result_to_dict(result: SettlementResult) -> dict:
    """정산 결과를 JSON-serializable dict로 변환 (웹 API용)"""
    return {
        "publisher": result.publisher,
        "period": result.period,
        "match_count": len(result.rows),
        "unmatched_count": len(result.unmatched),
        "match_rate": round(result.match_rate, 4),
        "total_amount": result.total_amount,
        "new_file_url": result.new_file_url,
        "rows": [
            {
                "contract_isbn": r.contract_isbn,
                "title": r.title,
                "usage_count": r.usage_count,
                "unit_price": r.unit_price,
                "amount": r.amount,
                "match_method": r.match_method,
            }
            for r in result.rows
        ],
        "unmatched": [
            {
                "usage_isbn": u.usage_isbn,
                "publisher": u.publisher,
                "book_name": u.book_name,
                "usage_count": u.usage_count,
                "unit_price": u.unit_price,
                "api_title": u.metadata.title if u.metadata else "",
                "api_author": u.metadata.author if u.metadata else "",
                "candidates": [
                    {
                        "isbn": book.isbn,
                        "title": book.title,
                        "publisher": book.publisher,
                        "score": round(score, 4),
                    }
                    for book, score in u.candidates
                ],
            }
            for u in result.unmatched
        ],
    }

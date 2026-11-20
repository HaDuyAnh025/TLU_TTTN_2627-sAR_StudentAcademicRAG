"""Điểm khớp cấu trúc: tiêu đề tài liệu (title / doc_heading) chứa đúng học kỳ / năm học / mã học phần / khóa đã trích từ câu hỏi."""
from __future__ import annotations

from rag.retrieval import normalize as N
from rag.retrieval.query_parser import ParsedQuery


def title_matches(payload: dict, pq: ParsedQuery) -> list[str]:
    """Các thuộc tính (đã trích từ câu hỏi) mà tiêu đề của chunk chứa đúng. Mỗi thuộc tính khớp được tính một lần."""
    title = " ".join(x for x in (payload.get("title"), payload.get("doc_heading")) if x)
    if not title:
        return []
    hit = []
    if pq.hoc_ky and pq.hoc_ky in N.find_hoc_ky(title):
        hit.append("hoc_ky")
    if pq.nam_hoc and pq.nam_hoc in {f"{a}_{b}" for a, b in N.find_nam_hoc(title)}:
        hit.append("nam_hoc")
    if pq.ma_hoc_phan and any(m in title.upper() for m in pq.ma_hoc_phan):
        hit.append("ma_hoc_phan")
    if pq.khoa_list and set(pq.khoa_list) & set(N.find_khoa(title)):
        hit.append("khoa")
    return hit

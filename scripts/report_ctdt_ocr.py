"""Đếm trang OCR nghi có bảng (ocr_table_suspect) của tài liệu ctdt in_scope và ước tính token ảnh gpt-4o-mini vision. Chỉ đọc."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.chunking.loader import iter_documents  # noqa: E402
from rag.chunking.metadata import load_doc_metas  # noqa: E402
from rag.config import chunking_config  # noqa: E402

# gpt-4o-mini vision: base 2833 + 5667/ô 512px (detail=high); detail=low: 2833. Trang A4 thu về cạnh ngắn 768px -> 768x1086 -> 2x3 ô.
BASE, TILE, TILES_A4 = 2833, 5667, 6


def main() -> None:
    cfg = chunking_config()
    P = cfg["paths"]
    metas = load_doc_metas(P["doc_meta"], P["manifest"])
    pages = []
    docs = set()
    n_ocr_pages = 0
    for doc in iter_documents(P["clean_dir"]):
        m = metas.get(doc.doc_id)
        if m is None or m.doc_type != "ctdt" or not m.in_scope or m.trung_voi:
            continue
        for sp in doc.spans:
            if sp.route != "ocr":
                continue
            n_ocr_pages += 1
            if doc.ocr_table_suspect(sp.start, sp.end):
                bars = sum(1 for l in doc.text[sp.start:sp.end].split("\n") if "|" in l)
                pages.append((doc.doc_id, m.title, sp.page, bars))
                docs.add(doc.doc_id)
    pages.sort(key=lambda r: -r[3])
    out = P["out_dir"] / "ctdt_ocr_suspect_pages.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_id", "title", "page", "so_dong_co_|"])
        w.writerows(pages)
    n = len(pages)
    print(f"ctdt in_scope: tài liệu có trang OCR nghi bảng = {len(docs)}; tổng trang OCR của ctdt in_scope = {n_ocr_pages}; trang nghi bảng = {n}")
    print(f"ước tính token ảnh (gpt-4o-mini, A4): high = {n * (BASE + TILE * TILES_A4):,}; low = {n * BASE:,}")
    print("5 trang nhiều dòng '|' nhất:")
    for d, t, pg, b in pages[:5]:
        print(f"  {d} | {t[:60]} | trang {pg} | {b} dòng")


if __name__ == "__main__":
    main()

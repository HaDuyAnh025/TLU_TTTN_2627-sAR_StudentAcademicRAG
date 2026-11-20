"""Đọc lại bảng ctdt bằng VLM (xem rag/ingestion/table_vlm.py).

  python scripts/run_table_vlm.py --pilot     # 10 trang chạy thử: trang 50, 51 của drive-17ALNSt37... + trang nhiều "|" nhất của 8 tài liệu khác
  python scripts/run_table_vlm.py --all       # toàn bộ trang trong data/processed/ctdt_ocr_suspect_pages.csv (CHỈ chạy sau khi được duyệt)
  python scripts/run_table_vlm.py --check     # chỉ ghi lại table_vlm_check.csv từ lớp table_vlm/ đã có
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import chunking_config  # noqa: E402
from rag.ingestion.table_vlm import read_pages, write_check_csv, write_spot_check  # noqa: E402

FIRST = "drive-17ALNSt37-HO-NgV3cMygvmVuK0nB0psL"


def candidates() -> list[tuple[str, int, int]]:
    f = chunking_config()["paths"]["out_dir"] / "ctdt_ocr_suspect_pages.csv"
    return [(r["doc_id"], int(r["page"]), int(r["so_dong_co_|"])) for r in csv.DictReader(f.open(encoding="utf-8-sig"))]


REVIEW = {"drive-17ALNSt37-HO-NgV3cMygvmVuK0nB0psL": [2, 7, 8, 12, 14, 23, 34, 44, 58],
          "drive-195f57wSWF1hZEwuF6BXtpVeMrw24OYYf": [20, 41]}  # số trang 1-based


def export_review_images() -> None:
    """Ảnh trang (dpi 110) + bản Markdown VLM tương ứng (nếu có) vào data/processed/table_vlm_samples/can_soat/."""
    import json

    from rag.ingestion.loader import FILES_DIR
    from rag.ingestion.ocr_engines import render_pdf_page

    cc = chunking_config()
    dest = cc["paths"]["out_dir"] / "table_vlm_samples" / "can_soat"
    dest.mkdir(parents=True, exist_ok=True)
    for doc_id, pages in REVIEW.items():
        vf = cc["paths"]["table_vlm_dir"] / f"{doc_id}.json"
        vlm = {p["page"]: p for p in json.loads(vf.read_text(encoding="utf-8"))["pages"]} if vf.exists() else {}
        for pg in pages:
            render_pdf_page(FILES_DIR / f"{doc_id}.pdf", pg - 1, 110).save(dest / f"{doc_id[:16]}_p{pg}.png")
            if pg - 1 in vlm:
                (dest / f"{doc_id[:16]}_p{pg}.md").write_text(vlm[pg - 1]["text"], encoding="utf-8")
            print(f"{doc_id[:16]} trang {pg}: ảnh" + (" + md" if pg - 1 in vlm else " (trang không có trong table_vlm/)"))
    print(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--all", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--review-images", action="store_true", help="xuất ảnh cần soát vào data/processed/table_vlm_samples/can_soat/")
    g.add_argument("--spot", action="store_true", help="xuất data/processed/table_vlm_spot_check.md")
    a = ap.parse_args()
    if a.check:
        print(write_check_csv())
        for r in csv.DictReader(chunking_config()["paths"]["table_vlm_check"].open(encoding="utf-8-sig")):
            if float(r["ocr_recall"]) < 0.7:
                print(f"ocr_recall<0.7: {r['doc_id']} trang {r['page']} recall={r['ocr_recall']} match={r['match_rate']} need_review={r['need_review']}")
        return
    if a.review_images:
        export_review_images()
        return
    if a.spot:
        print(write_spot_check())
        return
    cands = candidates()
    if a.pilot:
        targets = [(FIRST, 50), (FIRST, 51)]
        seen = {FIRST}
        for d, p, _ in sorted(cands, key=lambda r: -r[2]):
            if d not in seen and len(targets) < 10:
                targets.append((d, p))
                seen.add(d)
    else:
        targets = [(d, p) for d, p, _ in cands]
    print(f"{len(targets)} trang")
    print(read_pages(targets))


if __name__ == "__main__":
    main()

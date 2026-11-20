"""Sinh bản nháp metadata tài liệu: configs/doc_meta.draft.yaml và data/processed/pages_candidates.csv.

Chỉ ĐỌC data/interim/clean và data/raw; chỉ GHI configs/doc_meta.draft.yaml và data/processed/pages_candidates.csv.
Người duyệt bản nháp rồi đổi tên thành configs/doc_meta.yaml.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from rag.chunking.classify import DOC_TYPES, classify  # noqa: E402
from rag.chunking.loader import iter_documents  # noqa: E402
from rag.chunking.procedural import extract_heading, extract_issued_date  # noqa: E402
from rag.config import ROOT, chunking_config  # noqa: E402

DIEU = re.compile(r"^Điều\s+\d+\s*[.:]", re.M)
SKIP_URL = ("/gioi-thieu", "/cong-khai")


def pick_url(urls: list[str]) -> str | None:
    """Ưu tiên URL /thong-bao/, bỏ /gioi-thieu và /cong-khai."""
    for u in urls:
        if "/thong-bao/" in u:
            return u
    for u in urls:
        if not u.rstrip("/").endswith(SKIP_URL):
            return u
    return urls[0] if urls else None


def hints(heading: str | None, text: str) -> list[str]:
    """Gợi ý khóa/ngành rút từ tiêu đề + 1500 ký tự đầu (chỉ để người điền tay)."""
    s = (heading or "") + "\n" + text[:1500]
    out = [m.group(0) for m in re.finditer(r"(?i)\b(kh[óo]a|k)\s*\d{2}(\s*(,|-|và)\s*\d{2})*", s)]
    out += [m.group(0).strip() for m in re.finditer(r"(?i)ngành\s+[A-ZĐ][^,.;:\n]{3,50}", s)]
    return list(dict.fromkeys(out))[:6]


def main() -> None:
    cfg = chunking_config()
    by_file: dict[str, list[dict]] = {}
    for line in cfg["paths"]["manifest"].read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        for f in m["files"]:
            by_file.setdefault(Path(f).name, []).append(m)

    docs: dict[str, dict] = {}
    unsure: dict[str, dict] = {}
    for doc in iter_documents(cfg["paths"]["clean_dir"]):
        ms = by_file.get(doc.file, [])
        urls = [m["url"] for m in ms]
        man_title = next((m["title"] for m in ms if m["title"] != "Thang Long University"), "")
        heading = extract_heading(doc.text)
        dtype, reasons, sure = classify(heading, bool(DIEU.search(doc.text)), man_title)
        if heading is None and man_title:  # không trích được tiêu đề: thử theo title manifest nhưng luôn đánh dấu chưa chắc
            dtype2, reasons2, _ = classify(man_title, bool(DIEU.search(doc.text)))
            dtype, reasons, sure = dtype2, ["theo title manifest: " + "; ".join(reasons2)], False
        if heading and len(heading) < 40 and man_title:
            sure = False
            reasons.append("tiêu đề trích được quá ngắn, so với title manifest")
        if heading and "?" in heading:
            sure = False
            reasons.append("tiêu đề có '?' (nghi lỗi OCR)")
        entry = {
            "file": doc.file,
            "doc_type": dtype,
            "in_scope": dtype != "khac",
            "do_chac": "chac" if sure else "chua_chac",
            "ly_do": "; ".join(reasons),
            "tieu_de": heading,
            "title": heading or man_title or None,
            "doc_heading": heading,
            "source_url": pick_url(urls),
            "source_urls": urls,
            "posted_date": next((m["date"] for m in ms if m.get("date")), None),
            "issued_date": extract_issued_date(doc.text),
            "status": "hieu_luc",
            "khoa_tu": None,
            "khoa_den": None,
            "nganh": None,
            "goi_y_khoa": hints(heading, doc.text),
        }
        docs[doc.doc_id] = entry
        if not sure:
            unsure[doc.doc_id] = {"doc_type": dtype, "ly_do": entry["ly_do"], "tieu_de": heading, "title_manifest": man_title}

    header = (
        "# BẢN NHÁP metadata tài liệu - tạo bởi scripts/make_doc_meta_draft.py. Duyệt rồi đổi tên thành configs/doc_meta.yaml.\n"
        "# Quy ước: khoa_tu / khoa_den / nganh = null nghĩa là 'áp dụng cho tất cả' (retrieval phải coi null là khớp).\n"
        "# goi_y_khoa chỉ là gợi ý rút từ nội dung, KHÔNG tự điền vào khoa_tu/khoa_den/nganh.\n"
        "# doc_type thuộc enum: " + " | ".join(DOC_TYPES) + "\n"
        "# Mục `chua_chac` liệt kê các tài liệu cần xem trước; sửa doc_type ngay trong mục `docs`.\n\n"
    )
    body = yaml.safe_dump({"chua_chac": unsure, "docs": docs}, allow_unicode=True, sort_keys=False, width=200)
    (ROOT / "configs" / "doc_meta.draft.yaml").write_text(header + body, encoding="utf-8")

    rows = []
    for f in sorted((ROOT / "data" / "raw" / "pages").rglob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        t = d.get("text", "")
        if len(t) >= 200:
            rows.append([f.relative_to(ROOT).as_posix(), d.get("topic"), d.get("url"), len(t), t[:100].replace("\n", " ")])
    csv_path = cfg["paths"]["out_dir"] / "pages_candidates.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["page_file", "topic", "url", "n_chars", "first_100"])
        w.writerows(rows)

    print("docs:", len(docs), "chua_chac:", len(unsure))
    print(Counter(e["doc_type"] for e in docs.values()))
    print("pages_candidates:", len(rows), "->", csv_path)


if __name__ == "__main__":
    main()

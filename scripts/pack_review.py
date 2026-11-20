"""Đóng gói để GỬI cho người duyệt. Gói CHỈ gồm những gì giao diện duyệt cần cho phần của họ:
  - vài module xử lý dữ liệu (không có crawler, RAG, embedding, ...), cấu hình OCR, 1 file chạy review.py
  - các file gốc, kết quả trích xuất và lớp hiệu chỉnh CỦA CÁC FILE THUỘC PHẦN HỌ (không có file của phần khác)
KHÔNG gồm: .env (khóa API), khóa SSH, dữ liệu crawl, README/tài liệu nội bộ, ảnh/đầu ra giao diện cũ.

    python scripts/pack_review.py --part 2/3     # tạo ../sar_review_phan2_3.zip
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rag.ingestion.corrections import CORR_DIR, _load  # noqa: E402
from rag.ingestion.corrections_ui import in_part, part_map  # noqa: E402
from rag.ingestion.loader import FILES_DIR  # noqa: E402

# module cần cho giao diện duyệt (đã kiểm: đây là toàn bộ các module rag.* được nạp khi chạy giao diện)
MODULES = ["config.py", "evaluation/extract_eval.py", "evaluation/llm_review.py", "evaluation/review_pack.py",
           "ingestion/corrections.py", "ingestion/corrections_ui.py", "ingestion/loader.py",
           "ingestion/ocr_engines.py", "ingestion/vlm_ocr.py"]
GUIDE_FILE = ROOT / "docs" / "HUONG_DAN_DUYET.md"
REVIEW_PY = '''"""Chạy giao diện duyệt:  python review.py --part {PART}"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from rag.ingestion.corrections_ui import serve  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--part", default="{PART}", help="i/n, ví dụ 1/2")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--no-browser", action="store_true")
a = ap.parse_args()
i, n = (int(x) for x in a.part.split("/"))
serve(port=a.port, open_browser=not a.no_browser, part=(i - 1, n))
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True, help="i/n, ví dụ 2/3")
    args = ap.parse_args()
    i, n = (int(x) for x in args.part.split("/"))
    part = (i - 1, n)
    pm = part_map(n)
    layer = _load(CORR_DIR)
    mine = {pid: r for pid, r in layer.items() if in_part(r, part, pm)}
    files = sorted({r["file"] for r in mine.values()})
    out = ROOT.parent / f"sar_review_phan{i}_{n}.zip"
    n_files = n_ext = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "configs" / "ocr.yaml", "configs/ocr.yaml")
        z.write(ROOT / "requirements-review.txt", "requirements-review.txt")
        for m in MODULES:
            z.write(ROOT / "src" / "rag" / m, f"src/rag/{m}")
        z.writestr("review.py", REVIEW_PY.replace("{PART}", args.part))
        ext = ROOT / "data" / "interim" / "extract"
        for name in files:
            for suffix in (".json", ".json.sha256"):
                f = ext / (Path(name).stem + suffix)
                if f.exists():
                    z.write(f, f.relative_to(ROOT).as_posix())
                    n_ext += 1
            f = FILES_DIR / name
            if f.exists():
                z.write(f, f.relative_to(ROOT).as_posix())
                n_files += 1
        for pid in sorted(mine):
            for suffix in (".json", ".json.sha256"):
                f = CORR_DIR / (pid + suffix)
                z.write(f, f.relative_to(ROOT).as_posix())
        z.writestr(f"data/interim/phan_viec_{n}.json",  # chỉ các file của phần này
                   json.dumps({k: v for k, v in pm.items() if k in set(files)}, ensure_ascii=False, indent=1))
        guide = GUIDE_FILE.read_text(encoding="utf-8").replace("{PART_FILE}", f"{i}_{n}").replace("{PART}", args.part)
        z.writestr("HUONG_DAN.md", guide)
    print(f"Đã tạo {out} ({out.stat().st_size / 1e6:.0f} MB): {len(files)} file, {len(mine)} trang, "
          f"{n_files} file gốc, {n_ext} file trích xuất; không có .env")


if __name__ == "__main__":
    main()

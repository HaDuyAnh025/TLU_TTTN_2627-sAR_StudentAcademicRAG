"""So sánh các công cụ OCR trên một mẫu trang phủ các trường hợp của tập dữ liệu.

Cách dùng (chạy từ thư mục gốc dự án):
    python scripts/ocr_benchmark.py setup            # tải dữ liệu tiếng Việt cho Tesseract (1 lần)
    python scripts/ocr_benchmark.py sample           # chọn mẫu → data/eval/ocr_sample.json
    python scripts/ocr_benchmark.py run              # chạy OCR (chạy lại được, bỏ qua phần đã xong)
    python scripts/ocr_benchmark.py report           # → data/eval/ocr_report.md
    python scripts/ocr_benchmark.py all              # sample + run + report

Tùy chọn:
    --engines tesseract rapidocr:ppocrv5   chỉ chạy các công cụ này
    --limit 5                              chỉ chạy 5 mẫu đầu (thử nhanh)
    --force                                chạy lại cả phần đã có kết quả
    --rescan                               quét lại toàn bộ PDF khi chọn mẫu

Thêm công cụ mới: viết lớp có phương thức run(img) trong src/rag/ingestion/ocr_engines.py,
rồi khai báo ở configs/ocr.yaml. Chỉnh số trang mẫu, DPI, từ khóa ưu tiên cũng ở configs/ocr.yaml.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import load_config  # noqa: E402
from rag.evaluation import ocr_benchmark as bm  # noqa: E402
from rag.ingestion.ocr_engines import setup_tessdata  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["setup", "stats", "sample", "run", "report", "all"])
    ap.add_argument("--engines", nargs="+")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--rescan", action="store_true")
    args = ap.parse_args()
    cfg = load_config("ocr")

    if args.command == "setup":
        d = setup_tessdata(cfg.get("tesseract", {}).get("tessdata_variant", "best"),
                           cfg.get("tesseract", {}).get("tessdata_dir"))
        print(f"Đã sẵn sàng dữ liệu Tesseract tại: {d}")
        return
    if args.command == "stats":
        rows = bm.scan_pdf_pages(force=True)
        print(f"Đã quét {len(rows)} trang → {bm.STATS_PATH}")
        return
    if args.command in ("sample", "all"):
        s = bm.build_sample(cfg, rescan=args.rescan)
        print(f"Đã chọn {len(s['items'])} mẫu → {bm.SAMPLE_PATH}")
        for it in s["items"]:
            print(f"  {it['stratum']:<34} {it['id']}")
    if args.command in ("run", "all"):
        bm.run_benchmark(cfg, args.engines, force=args.force, limit=args.limit)
    if args.command in ("report", "all"):
        bm.make_report()
        print(f"Đã viết báo cáo → {bm.REPORT_PATH}")


if __name__ == "__main__":
    main()

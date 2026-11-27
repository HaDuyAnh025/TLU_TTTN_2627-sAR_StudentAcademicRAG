"""Điểm chạy ingest. Các bước: `crawl`, `extract`, `verify`, `vlm` (tùy chọn); clean/chunk/embed nối thêm sau.

Cách dùng:
    python scripts/ingest.py                    # crawl dữ liệu mới (--stage crawl)
    python scripts/ingest.py --stage extract    # trích text + OCR mọi PDF, ảnh → data/interim/extract (chạy lại được)
    python scripts/ingest.py --stage verify     # kiểm chứng kết quả đầy đủ, khớp mã băm, không bị sửa tay
    python scripts/ingest.py --stage evaluate   # thống kê, đánh giá dữ liệu sau OCR → data/eval/extract_report.md
    python scripts/ingest.py --stage review-pack   # chọn mẫu kiểm tra tay → data/eval/review_pack/ (mở index.html)
    python scripts/ingest.py --stage review-score  # tính tỷ lệ sai từ CSV bạn đã điền → data/eval/review_score.md
    python scripts/ingest.py --stage llm-review    # LLM rà soát OCR (--scope pack|flagged|all-ocr, --limit N, --dry-run)
    python scripts/ingest.py --stage review-items  # dựng trang web xác nhận TỪNG CHỖ nghi ngờ → data/eval/review_items/
    python scripts/ingest.py --stage review-items-score  # tính kết quả từ CSV đã điền → data/eval/review_items_score.md
    python scripts/ingest.py --stage llm-review --scope flagged   # LLM rà soát các trang đang bị gắn cờ
    python scripts/ingest.py --stage corrections-build            # LLM sửa trước → lớp hiệu chỉnh data/interim/corrected
    python scripts/ingest.py --stage table-vlm-review-ui         # giao diện duyệt bảng VLM (ảnh | VLM | OCR cũ) -> configs/table_vlm_fixes.yaml + log
    python scripts/ingest.py --stage corrections-ui               # giao diện: Văn bản gốc | LLM sửa | Đúng/Sai | Sửa sai + Accept
    python scripts/ingest.py --stage corrections-ui --part 2/3    # chia 3 người, mỗi người một phần (theo trang)
    python scripts/ingest.py --stage corrections-merge --from <corrected của người kia>   # gộp kết quả
    python scripts/ingest.py --stage audit-build [--audit-pages 80]   # kiểm mẫu OCR trang không cờ: chọn mẫu + gói zip
    python scripts/ingest.py --stage audit-ui                         # giao diện kiểm mẫu (Accept/Reject từng dòng)
    python scripts/ingest.py --stage rescan-hints                 # rà soát lại trang OCR không cờ: luật phát hiện (không tốn API)
    python scripts/ingest.py --stage rescan-eval                  # đo luật trên kết quả kiểm mẫu của người
    python scripts/ingest.py --stage rescan-llm --workers 4       # LLM đối chiếu ảnh gốc (--dry-run để đếm; --limit N để chạy thử)
    python scripts/ingest.py --stage rescan-build                 # dựng lớp hiệu chỉnh riêng data/interim/corrected_rescan
    python scripts/ingest.py --stage rescan-ui                    # duyệt kết quả rescan
    python scripts/ingest.py --stage clean                        # văn bản sạch = OCR gốc + sửa đã duyệt (+ sửa chữ/dấu LLM chưa duyệt) → data/interim/clean
    python scripts/ingest.py --stage clean-verify                 # dựng lại và so với data/interim/clean
    python scripts/ingest.py --stage relabel-build                # (không xóa thư mục tạm khi còn mục chưa merge; --force để xóa) đưa chỗ đã duyệt nhưng chưa áp được ra duyệt lại theo cả dòng (--dry-run để đếm)
    python scripts/ingest.py --stage relabel-ui                   # duyệt các mục đó
    python scripts/ingest.py --stage relabel-merge                # đưa quyết định về các lớp hiệu chỉnh
    python scripts/ingest.py --stage corrections-verify           # kiểm chứng lớp hiệu chỉnh
    python scripts/ingest.py --stage index --config c1|c2|c3|c2_novlm|all --model small|large [--yes]   # embed + Qdrant; không --yes = dry-run
    python scripts/ingest.py --stage index --smoke                # 5 câu smoke test trên sar_c2 (dense + BM25)
    python scripts/ingest.py --stage chunk --config c1|c2|c3|all   # chunking → data/processed/chunks/*.jsonl (cần configs/doc_meta.yaml)
    python scripts/ingest.py --stage vlm        # (tùy chọn) VLM đọc lại trang bị gắn cờ; --dry-run để chỉ đếm
    python scripts/ingest.py --stage extract --files drive-1ABC --limit 3   # thử vài file
    python scripts/ingest.py --stage extract --base-engine vietocr:vgg_transformer --shard 0/3   # GPU, chạy song song
    python scripts/ingest.py --force         # crawl lại, ghi đè
    python scripts/ingest.py --since 2025    # chỉ thông báo từ năm 2025
    python scripts/ingest.py --show-browser  # mở cửa sổ trình duyệt để quan sát
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import load_config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="(crawl) crawl lại cả trang đã có trong manifest; (relabel-build) xóa và dựng lại thư mục tạm dù còn mục chưa merge")
    ap.add_argument("--since", type=int, help="chỉ lấy thông báo từ năm này (ghi đè configs)")
    ap.add_argument("--no-files", action="store_true", help="không tải file đính kèm")
    ap.add_argument("--show-browser", action="store_true")
    ap.add_argument("--stage", choices=["crawl", "extract", "verify", "evaluate", "review-pack", "review-score", "llm-review",
                                        "review-items", "review-items-score", "corrections-build", "corrections-queue",
                                        "corrections-import", "corrections-verify", "corrections-ui", "corrections-merge", "audit-build", "audit-ui", "llm-summary", "vlm",
                                        "rescan-hints", "rescan-eval", "rescan-llm", "rescan-build", "rescan-ui", "rescan-repair", "rescan-quality", "rescan-leftover", "clean", "clean-verify", "chunk", "index", "relabel-build", "relabel-ui", "relabel-merge", "table-vlm-review-ui"], default="crawl")
    ap.add_argument("--config", choices=["c1", "c2", "c3", "c2_novlm", "all"], default="all", help="(chunk) cấu hình chunking cần sinh; (index) cấu hình cần index (c2_novlm chỉ cho index)")
    ap.add_argument("--yes", action="store_true", help="(index) gọi API OpenAI và ghi Qdrant thật; không có thì chỉ dry-run")
    ap.add_argument("--no-frozen-check", action="store_true", help="(index) bỏ kiểm tra FROZEN.md (chỉ để chạy thử)")
    ap.add_argument("--sparse-only", action="store_true", help="(index) chỉ cập nhật vector sparse bm25, giữ dense, không gọi OpenAI")
    ap.add_argument("--smoke", action="store_true", help="(index) chạy 5 câu smoke test trên sar_c2 (dense + BM25), không index")
    ap.add_argument("--model", help="(llm-review) ghi đè tên mô hình của nhà cung cấp đang chọn trong configs/ocr.yaml; (index) small|large, mặc định small")
    ap.add_argument("--workers", type=int, default=1, help="(llm-review) số luồng gọi API song song (khuyến nghị 4)")
    ap.add_argument("--llm-dir", help="(llm-review/corrections-build) tên thư mục con trong data/eval để lưu/đọc kết quả LLM (mặc định llm_review)")
    ap.add_argument("--llm-dirs", nargs="+", help="(llm-summary) các thư mục kết quả cần so sánh")
    ap.add_argument("--port", type=int, default=8765, help="(corrections-ui) cổng máy chủ cục bộ")
    ap.add_argument("--part", help="(corrections-ui) chia việc: i/n, ví dụ 1/3 = bạn là người thứ 1 trong 3 người (chia theo trang)")
    ap.add_argument("--from", dest="from_dir", help="(corrections-merge) thư mục data/interim/corrected của người kia")
    ap.add_argument("--audit-pages", type=int, default=80, help="(audit-build) số trang lấy mẫu (mặc định 80)")
    ap.add_argument("--no-browser", action="store_true", help="(corrections-ui) không tự mở trình duyệt")
    ap.add_argument("--scope", choices=["pack", "flagged", "all-ocr"], default="pack",
                    help="(llm-review) trang cần LLM rà soát: pack = 100 trang của gói mẫu; flagged = trang bị gắn cờ; all-ocr = mọi trang OCR")
    ap.add_argument("--audit-n", type=int, default=15, help="(review-items) số trang 'LLM bảo sạch' đưa vào để kiểm tra bỏ sót")
    ap.add_argument("--files", nargs="+", help="(extract) chỉ xử lý file có tên chứa chuỗi này")
    ap.add_argument("--limit", type=int, help="(extract/vlm) giới hạn số file/trang")
    ap.add_argument("--shard", help="(extract) i/n: chỉ xử lý phần i trong n phần, để chạy song song, ví dụ 0/3")
    ap.add_argument("--base-engine", help="(extract) ghi đè pipeline.base_engine, ví dụ vietocr:vgg_transformer")
    ap.add_argument("--no-review", action="store_true", help="(evaluate) không xuất ảnh mẫu kiểm tra tay")
    ap.add_argument("--review-csv", help="(review-score) đường dẫn CSV đã điền (mặc định data/eval/review_pack/review_sheet_filled.csv)")
    ap.add_argument("--dry-run", action="store_true", help="(vlm) chỉ đếm, không gọi")
    args = ap.parse_args()

    if args.stage == "index":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        from rag.embedding import indexer
        model = args.model or "small"
        if model not in ("small", "large"):
            raise SystemExit("--model của stage index phải là small hoặc large")
        if args.sparse_only:
            indexer.run_sparse_only(args.config, args.yes, frozen_check=not args.no_frozen_check)
        elif args.smoke:
            indexer.smoke(model)
        else:
            indexer.run_index(args.config, model, args.yes, frozen_check=not args.no_frozen_check)
        return
    if args.stage == "chunk":
        if args.config == "c2_novlm":
            raise SystemExit("c2_novlm chỉ dùng cho --stage index (file chunk đã có sẵn)")
        from rag.chunking.splitter import chunk_corpus
        only = {Path(f).stem for f in args.files} if args.files else None
        print(json.dumps(chunk_corpus(args.config, only=only), ensure_ascii=False, indent=1))
        return
    if args.stage == "table-vlm-review-ui":
        from rag.ingestion.table_vlm_review_ui import serve
        serve(port=args.port, open_browser=not args.no_browser)
        return
    if args.stage == "corrections-ui":
        from rag.ingestion.corrections_ui import serve
        part = None
        if args.part:
            i, n = (int(x) for x in args.part.split("/"))
            if not (1 <= i <= n):
                raise SystemExit("--part phải dạng i/n với 1 <= i <= n, ví dụ 2/3")
            part = (i - 1, n)
        serve(port=args.port, open_browser=not args.no_browser, part=part)
        return
    if args.stage.startswith("relabel-"):
        from rag.ingestion import relabel
        if args.stage == "relabel-build":
            print(json.dumps(relabel.build(dry_run=args.dry_run, force=args.force), ensure_ascii=False, indent=1))
        elif args.stage == "relabel-ui":
            from rag.ingestion.corrections_ui import serve
            serve(port=args.port, open_browser=not args.no_browser, corr_dir=relabel.STAGE_DIR, ui_dir=relabel.UI_DIR)
        else:
            print(json.dumps(relabel.merge_back(dry_run=args.dry_run), ensure_ascii=False, indent=1))
        return
    if args.stage in ("clean", "clean-verify"):
        from rag.ingestion import cleaner
        if args.stage == "clean":
            print(json.dumps(cleaner.run(), ensure_ascii=False, indent=1))
            print(f"Đã ghi {cleaner.CLEAN_DIR} (xem _manifest.json)")
        else:
            rep = cleaner.verify()
            print(json.dumps(rep, ensure_ascii=False, indent=1))
            print("KẾT QUẢ: ĐẠT" if rep["ok"] else "KẾT QUẢ: CÓ VẤN ĐỀ")
            sys.exit(0 if rep["ok"] else 1)
        return
    if args.stage.startswith("rescan-"):
        from rag.evaluation import rescan
        if args.stage == "rescan-hints":
            print(json.dumps(rescan.run_hints(limit=args.limit), ensure_ascii=False, indent=1))
        elif args.stage == "rescan-eval":
            print(json.dumps(rescan.eval_on_audit(), ensure_ascii=False, indent=1))
        elif args.stage == "rescan-llm":
            rescan.run_rescan(limit=args.limit, dry_run=args.dry_run, model_override=args.model, workers=args.workers)
        elif args.stage == "rescan-repair":
            print(json.dumps({"bam_dung_chua_ap": rescan.repair_confirmed(dry_run=args.dry_run),
                              "lap_nhieu_lan": rescan.resolve_repeats(dry_run=args.dry_run)}, ensure_ascii=False, indent=1))
        elif args.stage == "rescan-leftover":
            print(rescan.add_audit_leftovers(dry_run=args.dry_run))
        elif args.stage == "rescan-quality":
            print(json.dumps(rescan.quality_after(), ensure_ascii=False, indent=1))
        elif args.stage == "rescan-build":
            from rag.ingestion.corrections import summarize
            print(f"Đã xây lớp hiệu chỉnh tại {rescan.RESCAN_CORR_DIR}: {rescan.build_layer(fresh=args.force)}")
            print(f"Tổng hợp: {summarize(rescan.RESCAN_CORR_DIR)}")
        else:
            from rag.ingestion.corrections_ui import serve
            serve(port=args.port, open_browser=not args.no_browser, corr_dir=rescan.RESCAN_CORR_DIR, ui_dir=rescan.RESCAN_UI_DIR)
        return
    if args.stage == "audit-build":
        from rag.evaluation.sample_audit import build
        print(build(n_pages=args.audit_pages))
        return
    if args.stage == "audit-ui":
        from rag.evaluation.audit_ui import serve as audit_serve
        from rag.evaluation.sample_audit import AUDIT_DIR
        audit_serve(AUDIT_DIR, port=args.port if args.port != 8765 else 8780, open_browser=not args.no_browser)
        return
    if args.stage == "corrections-merge":
        from rag.ingestion.corrections import merge_from, summarize
        if not args.from_dir:
            raise SystemExit("Cần --from <thư mục corrected của người kia>")
        print(f"Kết quả gộp: {merge_from(Path(args.from_dir))}")
        print(f"Tổng hợp lớp hiệu chỉnh: {summarize()}")
        return
    if args.stage == "corrections-build":
        from rag.config import EVAL_DIR
        from rag.ingestion.corrections import CORR_DIR, build, summarize
        st = build(llm_dir=(EVAL_DIR / args.llm_dir) if args.llm_dir else None, fresh=args.force)
        print(f"Đã xây lớp hiệu chỉnh tại {CORR_DIR}: {st}")
        print(f"Tổng hợp: {summarize()}")
        return
    if args.stage == "corrections-queue":
        from rag.ingestion.corrections import QUEUE_DIR, queue
        meta = queue()
        print(f"Đã dựng {QUEUE_DIR}: {meta}")
        print(f"Mở {QUEUE_DIR / 'index.html'}: sửa các chỗ cần bạn, kiểm tra mẫu các chỗ LLM đã tự sửa, bấm 'Xuất CSV', "
              "lưu thành review_items_filled.csv cùng thư mục, rồi chạy --stage corrections-import.")
        return
    if args.stage == "corrections-import":
        from rag.ingestion.corrections import import_human, summarize
        st = import_human(csv_path=args.review_csv)
        print(f"Đã nhập kết quả của bạn: {st}")
        print(f"Tổng hợp lớp hiệu chỉnh: {summarize()}")
        return
    if args.stage == "corrections-verify":
        from rag.ingestion.corrections import verify_layer
        rep = verify_layer()
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        print("KẾT QUẢ: ĐẠT" if rep["ok"] else "KẾT QUẢ: CÓ VẤN ĐỀ")
        sys.exit(0 if rep["ok"] else 1)
    if args.stage == "llm-summary":
        from rag.config import EVAL_DIR
        from rag.evaluation.llm_review import summarize_dirs
        print(summarize_dirs([EVAL_DIR / d for d in (args.llm_dirs or ["llm_review"])]))
        return
    if args.stage == "llm-review":
        from rag.config import EVAL_DIR
        from rag.evaluation.llm_review import run_review
        run_review(scope=args.scope, limit=args.limit, dry_run=args.dry_run, model_override=args.model, workers=args.workers,
                   out_dir=(EVAL_DIR / args.llm_dir) if args.llm_dir else None)
        return
    if args.stage == "review-items":
        from rag.evaluation.llm_review import ITEMS_DIR, build_items
        meta = build_items(audit_n=args.audit_n)
        print(f"Đã dựng {ITEMS_DIR}: {meta}")
        print(f"Mở {ITEMS_DIR / 'index.html'}, xác nhận từng chỗ, bấm 'Xuất CSV', lưu thành review_items_filled.csv cùng thư mục.")
        return
    if args.stage == "review-items-score":
        from rag.evaluation.llm_review import SCORE_MD as ISCORE, score_items
        print(score_items(args.review_csv))
        print(f"Đã lưu: {ISCORE}")
        return
    if args.stage == "extract":
        from rag.ingestion.loader import Pipeline
        ocfg = load_config("ocr")
        if args.base_engine:
            ocfg["pipeline"]["base_engine"] = args.base_engine
        shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None
        Pipeline(ocfg).run(args.files, args.limit, args.force, shard)
        return
    if args.stage == "verify":
        from rag.ingestion.loader import verify
        rep = verify()
        print(json.dumps(rep["stats"], ensure_ascii=False, indent=1))
        bad = {k: v for k, v in rep["problems"].items() if v}
        print("KẾT QUẢ: ĐẠT" if rep["ok"] else "KẾT QUẢ: CÓ VẤN ĐỀ")
        for k, v in bad.items():
            print(f"  {k}: {len(v)} (ví dụ: {v[:3]})")
        sys.exit(0 if rep["ok"] else 1)
    if args.stage == "evaluate":
        from rag.evaluation.extract_eval import REPORT, evaluate
        S = evaluate(review=not args.no_review)
        print(f"Đã viết báo cáo: {REPORT}")
        print(f"Tổng: {S['files']} file, {S['pages']} trang; OCR {S['ocr_pages']}; ứng viên VLM {S['vlm_candidate_pages']}")
        return
    if args.stage == "review-pack":
        from rag.evaluation.review_pack import PACK, build_pack
        meta = build_pack()
        print(f"Đã tạo gói kiểm tra tay: {PACK}")
        print(f"Tổng {meta['total']} trang. Tổng thể: {meta['population']}")
        print(f"Cỡ mẫu theo nhóm: {meta['sample_sizes']}")
        print(f"Mở {PACK / 'index.html'} bằng trình duyệt, điền, bấm 'Xuất CSV'.")
        return
    if args.stage == "review-score":
        from rag.evaluation.review_pack import SCORE_MD, score
        print(score(args.review_csv))
        print(f"Đã lưu: {SCORE_MD}")
        return
    if args.stage == "vlm":
        from rag.ingestion.vlm_ocr import run_vlm
        run_vlm(limit=args.limit, dry_run=args.dry_run)
        return

    from rag.ingestion.crawler import Crawler  # chỉ cần khi crawl (cần Playwright)

    cfg = load_config("sources")
    if args.since:
        cfg["crawl"]["announcements_since_year"] = args.since
    if args.no_files:
        cfg["crawl"]["download_files"] = False
    Crawler(cfg, force=args.force).run(headless=not args.show_browser)


if __name__ == "__main__":
    main()

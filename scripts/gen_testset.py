"""Sinh bộ câu hỏi đánh giá retrieval từ VĂN BẢN TÀI LIỆU (không từ chunk) và quản lý data/eval/questions.jsonl.

  python scripts/gen_testset.py                  # dry-run: số lần gọi, token ước tính, chi phí (KHÔNG gọi API)
  python scripts/gen_testset.py --yes            # gọi LLM (chạy tiếp được nếu hết quota), rồi hậu xử lý -> questions.jsonl (pending)
  python scripts/gen_testset.py --build          # chỉ hậu xử lý lại từ log thô (không gọi mạng)
  python scripts/gen_testset.py --split          # (SAU KHI duyệt xong) chia dev/test phân tầng theo seed; câu đã có split được giữ
  python scripts/gen_testset.py --merge a.jsonl b.jsonl   # gộp kết quả của nhiều người duyệt
  python scripts/gen_testset.py --stats          # số câu theo trạng thái / doc_type / type

Chỉ ĐỌC data/processed/docs/ và configs/; chỉ GHI data/eval/ (questions.jsonl, testset_gen/).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import ROOT  # noqa: E402
from rag.evaluation import testset as T  # noqa: E402
from rag.evaluation import testset_gen as G  # noqa: E402

FROZEN_MARK = re.compile(r"Nguồn:\s*clean sau khi gộp label")


def frozen_ok() -> tuple[bool, str]:
    p = ROOT / "data" / "processed" / "chunks" / "FROZEN.md"
    if not p.exists():
        return False, "không có data/processed/chunks/FROZEN.md"
    txt = p.read_text(encoding="utf-8")
    return bool(FROZEN_MARK.search(txt)), T.sha256_text(txt)[:16]


def print_stats(rows: list[dict]) -> None:
    print(f"Tổng {len(rows)} câu. Theo trạng thái: {dict(Counter(r['review']['status'] for r in rows))}")
    print("Theo split:", dict(Counter(r.get("split") or "-" for r in rows)))
    print("doc_type × type:")
    for (d, t), v in sorted(Counter((r["doc_type"], r["type"]) for r in rows).items()):
        print(f"  {d:16s} {t:14s} {v}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="gọi LLM thật")
    ap.add_argument("--build", action="store_true", help="chỉ hậu xử lý từ log thô")
    ap.add_argument("--split", action="store_true")
    ap.add_argument("--merge", nargs="+", metavar="FILE")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--skip-frozen-check", action="store_true", help="bỏ kiểm FROZEN.md mới (chỉ để thử)")
    ap.add_argument("--price-in", type=float, help="USD / 1 triệu token đầu vào (ghi đè configs/testset.yaml)")
    ap.add_argument("--price-out", type=float, help="USD / 1 triệu token đầu ra")
    ap.add_argument("--model", help="ghi đè mô hình (mặc định theo configs/ocr.yaml: vlm.openai.model)")
    ap.add_argument("--limit", type=int, help="chỉ gọi N lời gọi đầu (thử nhỏ)")
    a = ap.parse_args()

    cfg = T.testset_config()
    qpath, gdir = cfg["paths"]["questions"], cfg["paths"]["gen_dir"]
    gdir.mkdir(parents=True, exist_ok=True)

    if a.stats:
        return print_stats(T.load_questions(qpath))
    if a.split:
        rows = T.load_questions(qpath)
        added = T.assign_splits(rows, cfg["seed"], cfg["dev_frac"])
        T.save_questions(rows, qpath)
        print(f"Đã gán split: {added}. Tập test CHỈ chạy cuối để báo cáo; KHÔNG chỉnh tham số trên test.")
        return print_stats(rows)
    if a.merge:
        merged, st = T.merge_reviews(T.load_questions(qpath), [T.load_questions(Path(p)) for p in a.merge])
        T.save_questions(merged, qpath)
        print(f"Đã gộp: {st}")
        return print_stats(merged)

    if a.price_in is not None:
        cfg["generation"]["price_per_1m_tokens"]["input"] = a.price_in
    if a.price_out is not None:
        cfg["generation"]["price_per_1m_tokens"]["output"] = a.price_out
    model = a.model or G.gen_model(cfg)
    meta = G.load_doc_meta()
    docs = G.eligible_docs(meta)
    print(f"{len(docs)} tài liệu đủ điều kiện (in_scope, hiệu lực, đại học). Lập kế hoạch lời gọi (chọn đơn vị từ văn bản, seed={cfg['seed']}); mất ~1 phút...")
    calls = G.plan_calls(cfg, docs, meta)
    raw_path = gdir / "raw_calls.jsonl"
    raw = G.read_raw(raw_path)
    done = {r["call_id"] for r in raw}
    slim = []
    for c in calls:
        s = {k: v for k, v in c.items() if k not in ("prompt", "unit", "versions", "cand")}
        if "unit" in c:
            s["unit_id"] = c["unit"]["unit_id"]
        slim.append(s)
    (gdir / "plan.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")

    if not a.build:
        info = G.dry_run(calls, cfg, model, done)
        print("\n== DRY-RUN ==")
        print(f"mô hình: {info['model']}  (temperature=0)")
        print(f"số lời gọi cần chạy: {info['n_calls']} (đã có sẵn trong log: {info['n_done']}); theo loại: {info['by_kind']}")
        print(f"token ước tính: vào ~{info['input_tokens']:,}; ra ~{info['output_tokens']:,}")
        print("chi phí ước tính: " + (f"~{info['cost_usd']:.3f} USD" if info["cost_usd"] is not None else
                                      "CHƯA tính (điền price_per_1m_tokens trong configs/testset.yaml hoặc --price-in/--price-out)"))
        if not a.yes:
            print("\nChưa gọi API. Xác nhận bằng: python scripts/gen_testset.py --yes")
            return
        ok, why = frozen_ok()
        if not ok and not a.skip_frozen_check:
            raise SystemExit(f"CHƯA gọi API: FROZEN.md mới chưa có dòng 'Nguồn: clean sau khi gộp label…' ({why}). Chờ bộ chunk mới rồi chạy lại "
                             f"(hoặc --skip-frozen-check nếu chắc chắn).")
        chat = G.OpenAIChat(model, cfg["generation"]["temperature"], cfg["generation"]["max_completion_tokens"])
        todo = [c for c in calls if c["call_id"] not in done]
        if a.limit:
            todo = todo[: a.limit]
        res = G.run_calls(todo, chat, raw_path, model, cfg)
        if not chat.temperature_applied:
            print("Lưu ý: mô hình không nhận temperature=0; đã gọi với temperature mặc định (log ghi temperature=null).")
        if res["stopped"]:
            print(f"ĐÃ DỪNG ({res['stopped']}). Chạy tiếp: python scripts/gen_testset.py --yes")
        raw = G.read_raw(raw_path)

    existing = T.load_questions(qpath)
    ok_q, rejected = G.build_questions(calls, raw, cfg, docs, existing)
    T.save_questions(existing + ok_q, qpath)
    rej_path = gdir / "rejected.jsonl"
    rej_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rejected), encoding="utf-8")
    print("\n== KẾT QUẢ ==")
    print(G.summarize(ok_q, rejected))
    print("\n10 câu mẫu:")
    step = max(1, len(ok_q) // 10)
    for q in ok_q[::step][:10]:
        print(f"- [{q['doc_type']}/{q['type']}] {q['question']}  (trùng từ {q['lexical_overlap']})")
    print(f"\nĐã ghi {len(ok_q)} câu pending vào {qpath}; câu bị loại: {rej_path}")


if __name__ == "__main__":
    main()

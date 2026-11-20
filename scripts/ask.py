"""CLI debug retrieval (CHƯA gọi LLM).

    python scripts/ask.py "câu hỏi" --config c2 --mode hybrid_rerank [--khoa 38] [--bac dai_hoc] [--show-stages]
    python scripts/ask.py --quick-eval          # 5 câu smoke test x 4 chế độ x (có/không khóa 38) trên sar_c2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?")
    ap.add_argument("--config", default="c2", choices=["c1", "c2", "c3", "c2_novlm"])
    ap.add_argument("--mode", default="hybrid_rerank", choices=["dense", "bm25", "hybrid", "hybrid_rerank", "hybrid_rerank_fused"])
    ap.add_argument("--khoa", type=int, help="khóa của sinh viên (user_ctx); câu hỏi nêu khóa khác thì ưu tiên câu hỏi")
    ap.add_argument("--bac", help="bậc của sinh viên (user_ctx), ví dụ dai_hoc")
    ap.add_argument("--show-stages", action="store_true", help="in bảng xếp hạng từng giai đoạn (dense / bm25 / rrf / rerank)")
    ap.add_argument("--quick-eval", action="store_true")
    a = ap.parse_args()

    if a.quick_eval:
        from rag.retrieval.quick_eval import run
        print(run(a.config))
        return
    if not a.query:
        ap.error("cần câu hỏi hoặc --quick-eval")
    from rag.retrieval.retriever import Retriever
    ctx = {k: v for k, v in (("khoa", a.khoa), ("bac_dao_tao", a.bac)) if v is not None} or None
    r = Retriever().retrieve(a.query, a.config, a.mode, ctx)
    pq = r.parsed_query
    print(f"ParsedQuery: khoa={pq.khoa} bac={pq.bac_dao_tao} hoc_ky={pq.hoc_ky} nam_hoc={pq.nam_hoc} ma_hp={pq.ma_hoc_phan} flags={pq.flags}")
    print(f"Bộ lọc: {r.filters}")

    def table(stage: str, rows: list[dict], n: int = 10) -> None:
        print(f"\n-- {stage} (top {min(n, len(rows))}/{len(rows)})")
        for x in rows[:n]:
            print(f"  {x['rank']:2d} {x['score']:8.4f} [{x['khoa'][0]}-{x['khoa'][1]}] ...{x['chunk_id'][-30:]:30s} {x['breadcrumb'][:70]}")
    stages = ["dense", "bm25", "rrf", "rerank"] if a.show_stages else []
    for s in stages:
        if s in r.candidates:
            table(s, r.candidates[s])
    print(f"\n== KẾT QUẢ ({a.config}, {a.mode}) top {len(r.final)}")
    table("final", [{"rank": i, "score": c["final_score"], "khoa": [c["payload"].get("khoa_tu"), c["payload"].get("khoa_den")],
                     "chunk_id": c["chunk_id"], "breadcrumb": c["payload"]["embed_text"].split("] ")[0][1:]} for i, c in enumerate(r.final, 1)], 10)
    if r.duplicates:
        print(f"\nKhử trùng lặp: {[(d['kept'][-24:], len(d['dropped'])) for d in r.duplicates]}")
    print(f"\nmax_rerank_score: {r.max_rerank_score}  max_rerank_logit: {r.max_rerank_logit}")
    print(f"Context: {len(r.context['items'])} mục, {r.context['tokens']}/{r.context['budget']} token")
    for i, s in enumerate(r.context["sources"], 1):
        print(f"  [{i}] {s['breadcrumb'][:80]} | {s['doc_id']} | tr.{s['page_start']}-{s['page_end']}")
    print("Thời gian (s): " + ", ".join(f"{k}={v}" for k, v in r.timings.items()))


if __name__ == "__main__":
    main()

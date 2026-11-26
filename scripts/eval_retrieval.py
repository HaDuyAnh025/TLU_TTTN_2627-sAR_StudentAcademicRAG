"""Chạy bộ chấm retrieval trên bộ câu hỏi đã duyệt (data/eval/questions.jsonl). CHƯA gồm phần LLM sinh câu trả lời.

  python scripts/eval_retrieval.py                       # split dev, lưới c1/c2/c3 × 5 chế độ (+ c2_novlm cho nhóm ctdt-VLM, + dòng reranker gốc)
  python scripts/eval_retrieval.py --split test --final  # CHỈ chạy cuối để báo cáo; không chỉnh tham số theo kết quả này

Điều kiện chạy: Qdrant đã index lại theo FROZEN.md hiện tại - so sha256 từng file chunk trong FROZEN.md với sha ghi trong
data/processed/embedding_usage.jsonl của lần index gần nhất; lệch thì DỪNG và báo.
Ra: data/eval/results/<run_id>/{per_question.jsonl, summary.csv, summary.md, config.json, threshold_curves/}.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import ROOT  # noqa: E402
from rag.evaluation import retrieval_eval as E  # noqa: E402
from rag.evaluation import testset as T  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--final", action="store_true", help="bắt buộc khi --split test (chạy cuối để báo cáo)")
    ap.add_argument("--run-id")
    ap.add_argument("--questions", help="questions.jsonl (mặc định data/eval/questions.jsonl)")
    ap.add_argument("--configs", default="c1,c2,c3")
    ap.add_argument("--modes", default=",".join(E.MODES))
    ap.add_argument("--cover-thr", type=float, default=0.5)
    ap.add_argument("--no-ref", action="store_true", help="bỏ dòng reranker gốc (torch, 20, 512)")
    ap.add_argument("--ref-configs", default="c2", help="cấu hình chạy dòng reranker gốc (mặc định chỉ c2; torch trên CPU chậm)")
    ap.add_argument("--no-ablation", action="store_true", help="bỏ c2_novlm / c2(text) cho nhóm ctdt-VLM")
    ap.add_argument("--limit", type=int, help="chỉ N câu có đáp án đầu tiên (chạy thử)")
    ap.add_argument("--skip-gate", action="store_true", help="bỏ cổng kiểm index (CHỈ để thử trên máy dev; kết quả không dùng báo cáo)")
    a = ap.parse_args()
    if a.split == "test" and not a.final:
        raise SystemExit("Tập test chỉ chạy cuối để báo cáo: thêm --final nếu chắc chắn. KHÔNG chỉnh tham số dựa trên kết quả test.")

    from rag.embedding.settings import embedding_config
    from rag.retrieval.settings import retrieval_config
    ecfg, rcfg0 = embedding_config(), retrieval_config()
    chunks_dir = ROOT / "data" / "processed" / "chunks"
    frozen = chunks_dir / "FROZEN.md"
    gate = {"skipped": True} if a.skip_gate else E.check_index_gate(frozen, Path(ecfg["usage_log"]), chunks_dir)

    tcfg = T.testset_config()
    qpath = Path(a.questions) if a.questions else tcfg["paths"]["questions"]
    allq = T.load_questions(qpath)
    kept = [q for q in allq if q["review"]["status"] in T.SCORED]
    nosplit = [q["id"] for q in kept if not q.get("split")]
    if nosplit:
        raise SystemExit(f"{len(nosplit)} câu đã duyệt chưa có split (vd {nosplit[:3]}). Chạy: python scripts/gen_testset.py --split")
    qs = [q for q in kept if q["split"] == a.split and q["expected_behavior"] == "answer"]
    oos = [q for q in kept if q["split"] == a.split and q["expected_behavior"] == "refuse"]
    if a.limit:
        qs = qs[: a.limit]
    if not qs:
        raise SystemExit(f"Không có câu accepted/edited nào ở split={a.split}.")
    configs = [c for c in a.configs.split(",") if c]
    modes = [m for m in a.modes.split(",") if m]
    print(f"{len(qs)} câu có đáp án + {len(oos)} câu ngoài phạm vi ({a.split}); lưới {configs} × {modes}")

    from rag.evaluation.testset_gen import load_doc_meta, quy_che_versions, vlm_doc_ids
    version_docs = set(quy_che_versions(load_doc_meta()).values())
    vlm = vlm_doc_ids()
    vlm_qs = [q for q in qs if "ctdt_vlm" in q.get("flags", []) or any(e["doc_id"] in vlm for e in q["expected"])]
    for q in vlm_qs:
        if "ctdt_vlm" not in q.get("flags", []):
            q.setdefault("flags", []).append("ctdt_vlm")  # chỉ trong bộ nhớ: để gom nhóm trong summary

    # ---- retriever: chung client + embedder; hai biến thể reranker
    from rag.embedding.qdrant_store import connect
    from rag.retrieval.dense import QueryEmbedder
    from rag.retrieval.reranker import make_reranker
    from rag.retrieval.retriever import Retriever
    client = connect(ecfg["qdrant"]["url"])
    emb = E.CachedEmbedder(QueryEmbedder(ecfg))

    def variant(backend: str, n_rerank: int, max_len: int):
        rc = copy.deepcopy(rcfg0)
        rc["n_rerank"] = n_rerank
        rc["reranker"] = {**rc["reranker"], "backend": backend, "max_length": max_len}
        rr = E.CachingReranker(make_reranker(rc)) if any(m in E.RERANK_MODES for m in modes) else None
        return Retriever(ecfg, rc, client=client, embedder=emb, reranker=rr), rc

    rt_fast, rc_fast = variant("onnx", 10, 256)
    rt_ref = rc_ref = None
    if not a.no_ref:
        rt_ref, rc_ref = variant("torch", 20, 512)

    # ---- chỉ mục chunk
    ix = {c: E.ChunkIndex.load(ecfg["chunks"][c], ecfg["c3_parents"] if c == "c3" else None) for c in configs}
    ix_text: dict[str, E.ChunkIndex] = {}
    if not a.no_ablation and vlm_qs:
        ix_text["c2_novlm"] = E.ChunkIndex.load(ecfg["chunks"]["c2_novlm"], None, with_content=True)
        ix_text["c2"] = E.ChunkIndex.load(ecfg["chunks"]["c2"], None, with_content=True)

    run_id = a.run_id or f"{a.split}-{time.strftime('%Y%m%d-%H%M%S')}"
    out = ROOT / "data" / "eval" / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    pq_path = out / "per_question.jsonl"
    done = {(r["id"], r["label"], r["mode"]) for r in T.load_questions(pq_path)} if pq_path.exists() else set()

    # (nhãn, config, retriever, ix, cov_mode, câu hỏi, chế độ)
    jobs = [(c, c, rt_fast, ix[c], "char", qs + oos, modes) for c in configs]
    if rt_ref:
        rmodes = [m for m in modes if m in E.RERANK_MODES]
        jobs += [(f"{c}+torch(20,512)", c, rt_ref, ix[c], "char", qs + oos, rmodes) for c in a.ref_configs.split(",") if c in ix]
    if ix_text:
        jobs += [("c2_novlm(text)", "c2_novlm", rt_fast, ix_text["c2_novlm"], "text", vlm_qs, modes), ("c2(text)", "c2", rt_fast, ix_text["c2"], "text", vlm_qs, modes)]
    total = sum(len(j[5]) * len(j[6]) for j in jobs)
    print(f"{total} lượt chạy; run_id={run_id}")
    n = 0
    t0 = time.time()
    with pq_path.open("a", encoding="utf-8") as f:
        for label, config, rt, index, cov, qlist, mlist in jobs:
            for q in qlist:
                for mode in mlist:
                    n += 1
                    if (q["id"], label, mode) in done:
                        continue
                    rec = E.run_cell(rt, label, config, mode, q, index, a.cover_thr, cov, version_docs)
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    if n % 25 == 0:
                        print(f"  {n}/{total}  ({time.time() - t0:.0f}s)", flush=True)

    per_q = T.load_questions(pq_path)
    summ, lat = E.aggregate(per_q), E.step_latency([r for r in per_q if r.get("scored")])
    E.write_csv(out / "summary.csv", summ)
    table, curves = E.threshold_report(per_q)
    (out / "threshold_curves").mkdir(exist_ok=True)
    for name, cv in curves.items():
        E.write_csv(out / "threshold_curves" / f"{name}.csv", cv)
    ov = sorted(q["lexical_overlap"] for q in qs if q.get("lexical_overlap") is not None)
    extra = {"version": E.version_stats(per_q), "thresholds": table,
             "overlap": {"n": len(ov), "mean": round(sum(ov) / len(ov), 3), "median": ov[len(ov) // 2], "p90": ov[min(len(ov) - 1, int(0.9 * len(ov)))]} if ov else None}
    frozen_txt = frozen.read_text(encoding="utf-8")
    run = {"run_id": run_id, "split": a.split, "n_questions": len(qs), "n_oos": len(oos), "cover_thr": a.cover_thr, "frozen_sha": T.sha256_text(frozen_txt),
           "questions_sha": T.sha256_text(Path(qpath).read_text(encoding="utf-8")),
           "rerank_fast": f"{rc_fast['reranker']['backend']}, n_rerank={rc_fast['n_rerank']}, max_length={rc_fast['reranker']['max_length']}",
           "rerank_ref": (f"{rc_ref['reranker']['backend']}, n_rerank={rc_ref['n_rerank']}, max_length={rc_ref['reranker']['max_length']}" if rc_ref else "không chạy")}
    (out / "summary.md").write_text(E.summary_md(run, summ, lat, extra), encoding="utf-8")
    (out / "config.json").write_text(json.dumps({**run, "gate": gate, "configs": configs, "modes": modes, "frozen_md": frozen_txt,
                                                 "retrieval": {k: v for k, v in rcfg0.items() if k != "hf_cache_dir"}, "embedding_collections": ecfg["qdrant"]["collections"]},
                                                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Xong. {out / 'summary.md'}")


if __name__ == "__main__":
    main()

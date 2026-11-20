"""Đo và tối ưu reranker trên CPU. Mỗi giai đoạn ghi JSON vào data/eval/rerank_bench/ để giai đoạn sau dùng lại.

    python scripts/bench_rerank.py --stage env       # phiên bản torch, số luồng, nhân vật lý/logic, MKL/oneDNN
    python scripts/bench_rerank.py --stage threads   # luồng x batch x inference_mode (torch fp32, 20 cặp x 5 câu)
    python scripts/bench_rerank.py --stage export    # xuất ONNX + lượng tử hóa int8
    python scripts/bench_rerank.py --stage compare   # ONNX int8 so với torch fp32: Spearman, top-5
    python scripts/bench_rerank.py --stage sweep     # backend x n_rerank x max_length (thời gian trung vị + hạng chunk đúng)
    python scripts/bench_rerank.py --stage fused     # hybrid_rerank vs hybrid_rerank_fused (w, struct_bonus) từ logit đã lưu
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import EVAL_DIR  # noqa: E402

OUT = EVAL_DIR / "rerank_bench"
CTXS = [("-", None), ("k38", {"khoa": 38})]


def save(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load(name: str):
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


def get_pools(n: int = 20, ctxs=CTXS):
    """{(q_index, ctx_name): {query, ctx, pool (n ứng viên sau RRF + khử trùng lặp)}} từ Qdrant thật, chưa rerank."""
    from rag.retrieval.quick_eval import CASES
    from rag.retrieval.retriever import Retriever
    rt = Retriever()
    pools = {}
    for qi, (q, _, pred) in enumerate(CASES):
        for cname, ctx in ctxs:
            res, ranked, _, _ = rt.first_stage(q, "c2", "hybrid_rerank", ctx)
            pools[(qi, cname)] = {"query": res.parsed_query.text, "ctx": ctx, "pred": pred, "pool": ranked[:n], "pq": res.parsed_query}
    return rt, pools


def first_rank(order: list[int], pool: list[dict], pred) -> int | None:
    for r, i in enumerate(order, 1):
        if pred(pool[i]["payload"], None):
            return r
    return None


def stage_env() -> None:
    import psutil
    import torch
    info = {"torch": torch.__version__, "num_threads_default": torch.get_num_threads(), "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": os.cpu_count(), "mkl": torch.backends.mkl.is_available(), "onednn_mkldnn": torch.backends.mkldnn.is_available(),
            "openmp": torch.backends.openmp.is_available(), "ram_total_gb": round(psutil.virtual_memory().total / 1e9, 1),
            "ram_available_gb": round(psutil.virtual_memory().available / 1e9, 1)}
    try:
        import onnxruntime as ort
        info["onnxruntime"] = ort.__version__
        info["ort_providers"] = ort.get_available_providers()
    except Exception as e:  # noqa: BLE001
        info["onnxruntime"] = f"không có: {e}"
    print(json.dumps(info, ensure_ascii=False, indent=1))
    save("env", info)


def stage_threads() -> None:
    import psutil
    from rag.retrieval.reranker import make_reranker
    from rag.retrieval.settings import retrieval_config
    rt, pools = get_pools(20, CTXS[:1])
    rr = make_reranker(retrieval_config())
    phys, logical, default = psutil.cpu_count(logical=False), os.cpu_count(), rr.torch.get_num_threads()
    texts = {k: [c["payload"]["embed_text"] for c in v["pool"]] for k, v in pools.items()}
    rr.score_logits(next(iter(pools.values()))["query"], next(iter(texts.values()))[:4])  # khởi động (nạp thư viện, cấp phát bộ nhớ)
    combos = [("mặc định (luồng=%d, batch=16, inference_mode)" % default, dict(threads=default, batch=16, grad="inference_mode")),
              ("luồng = nhân vật lý (%d)" % phys, dict(threads=phys, batch=16, grad="inference_mode")),
              ("luồng = nhân logic (%d)" % logical, dict(threads=logical, batch=16, grad="inference_mode")),
              ("luồng = 8", dict(threads=8, batch=16, grad="inference_mode")),
              ("luồng = 6", dict(threads=6, batch=16, grad="inference_mode")),
              ("batch 20 (1 batch)", dict(threads=default, batch=20, grad="inference_mode")),
              ("không inference_mode (no_grad)", dict(threads=default, batch=16, grad="no_grad"))]
    rows = []
    for name, c in combos:
        rr.torch.set_num_threads(c["threads"])
        rr.batch_size, rr.grad_mode = c["batch"], c["grad"]
        ts = []
        for k, v in pools.items():
            t = time.perf_counter()
            rr.score_logits(v["query"], texts[k])
            ts.append(time.perf_counter() - t)
        rows.append({"cau_hinh": name, **c, "median_s": round(statistics.median(ts), 2), "mean_s": round(statistics.mean(ts), 2), "times": [round(x, 2) for x in ts]})
        print(f"{name:50s} median={rows[-1]['median_s']:6.2f}s mean={rows[-1]['mean_s']:6.2f}s  {rows[-1]['times']}", flush=True)
    best = min(rows, key=lambda r: r["median_s"])
    print("NHANH NHẤT:", best["cau_hinh"], best["median_s"], "s")
    save("threads", {"rows": rows, "best": best})


def best_threads() -> int | None:
    try:
        return load("threads")["best"]["threads"]
    except FileNotFoundError:
        return None


def best_grad() -> str:
    try:
        return load("threads")["best"]["grad"]
    except FileNotFoundError:
        return "inference_mode"


def stage_export() -> None:
    from rag.retrieval.onnx_export import export_int8
    from rag.retrieval.settings import retrieval_config
    cfg = retrieval_config()
    t = time.perf_counter()
    p = export_int8(cfg["reranker"]["model"], cfg["hf_cache_dir"])
    size = sum(f.stat().st_size for f in p.parent.glob("*") if f.is_file()) / 1e9
    print(f"Đã ghi {p} ({size:.2f} GB tổng thư mục onnx/) trong {time.perf_counter() - t:.0f}s")
    save("export", {"path": str(p), "gb": round(size, 2), "seconds": round(time.perf_counter() - t)})


def stage_compare() -> None:
    from scipy.stats import spearmanr
    from rag.retrieval.reranker import make_reranker
    from rag.retrieval.settings import retrieval_config
    cfg = retrieval_config()
    rt, pools = get_pools(20, CTXS[:1])
    th = best_threads()
    tr = make_reranker(cfg, threads=th, grad_mode=best_grad())
    ox = make_reranker(cfg, backend="onnx", threads=th)
    rows = []
    for k, v in pools.items():
        texts = [c["payload"]["embed_text"] for c in v["pool"]]
        a, b = tr.score_logits(v["query"], texts), ox.score_logits(v["query"], texts)
        ra, rb = sorted(range(len(a)), key=lambda i: -a[i]), sorted(range(len(b)), key=lambda i: -b[i])
        rho = float(spearmanr(a, b).statistic)
        rows.append({"q": v["query"], "spearman": round(rho, 4), "top5_same_order": ra[:5] == rb[:5], "top5_same_set": set(ra[:5]) == set(rb[:5]),
                     "mean_abs_logit_diff": round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 3),
                     "torch_top1": ra[0], "onnx_top1": rb[0]})
        print(rows[-1], flush=True)
    save("compare", rows)


def stage_sweep() -> None:
    from rag.retrieval.reranker import make_reranker
    from rag.retrieval.settings import retrieval_config
    cfg = retrieval_config()
    rt, pools = get_pools(20)
    th = best_threads()
    res, logits = [], {}
    for backend in ("torch", "onnx"):
        rr = make_reranker(cfg, backend=backend, threads=th, grad_mode=best_grad())
        v0 = next(iter(pools.values()))
        rr.score_logits(v0["query"], [c["payload"]["embed_text"] for c in v0["pool"]][:4])  # khởi động
        for ml in (256, 384, 512):
            rr.max_length = ml
            for n in (10, 20):
                ts, ranks = [], {}
                for (qi, cname), v in pools.items():
                    texts = [c["payload"]["embed_text"] for c in v["pool"][:n]]
                    t = time.perf_counter()
                    lg = rr.score_logits(v["query"], texts)
                    ts.append(time.perf_counter() - t)
                    order = sorted(range(len(lg)), key=lambda i: -lg[i])
                    ranks[f"{qi + 1}{cname}"] = first_rank(order, v["pool"][:n], v["pred"])
                    if n == 20:
                        logits[f"{backend}|{ml}|{qi}|{cname}"] = lg
                row = {"backend": backend, "max_length": ml, "n_rerank": n, "median_s": round(statistics.median(ts), 2),
                       "mean_s": round(statistics.mean(ts), 2), "ranks": ranks}
                res.append(row)
                print(f"{backend:5s} ml={ml} n={n:2d} median={row['median_s']:6.2f}s ranks={ranks}", flush=True)
        save("sweep", {"rows": res, "threads": th})
        save("logits", logits)
        del rr


def stage_fused() -> None:
    from rag.retrieval.fusion import fuse_with_rerank
    from rag.retrieval.reranker import sigmoid
    rt, pools = get_pools(20)
    logits = load("logits")
    out = []
    for backend in ("torch", "onnx"):
        for (qi, cname), v in pools.items():
            lg = logits.get(f"{backend}|512|{qi}|{cname}")
            if lg is None:
                continue
            pool, probs = v["pool"], [sigmoid(x) for x in lg]
            row = {"backend": backend, "q": qi + 1, "ctx": cname,
                   "hybrid": first_rank(list(range(len(pool))), pool, v["pred"]),
                   "hybrid_rerank": first_rank(sorted(range(len(lg)), key=lambda i: -lg[i]), pool, v["pred"])}
            for w in (0.5, 0.7):
                for bonus in (0.0, 0.003):
                    f = fuse_with_rerank(pool, probs, v["pq"], w, bonus)
                    row[f"fused_w{w}_b{bonus}"] = first_rank(list(range(len(f))), f, v["pred"])
            out.append(row)
            print(row, flush=True)
    save("fused", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=["env", "threads", "export", "compare", "sweep", "fused"])
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    globals()[f"stage_{a.stage}"]()

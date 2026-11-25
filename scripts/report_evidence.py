"""In ra các chỉ số làm bằng chứng cho báo cáo (Embedding + Vector DB, Retriever + Rerank). Chỉ ĐỌC, không ghi, không gọi OpenAI.

    python scripts/report_evidence.py                 # các mục đọc từ file (không cần Qdrant)
    python scripts/report_evidence.py --live          # thêm các mục cần Qdrant đang chạy (số điểm, lọc khóa, status, mẫu ngẫu nhiên)
    python scripts/report_evidence.py --section usage rerank   # chỉ in một số mục

Mục: files | usage | bm25 | quick | rerank | live
"""
import argparse
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import ROOT, EVAL_DIR  # noqa: E402
from rag.embedding.settings import embedding_config  # noqa: E402

CFG = embedding_config()
BENCH = EVAL_DIR / "rerank_bench"


def h(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def jl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ files
def sec_files() -> None:
    """Bảng 3: số dòng và sha256 từng file chunk, đối chiếu FROZEN.md; chunk bị loại; không chunk nào in_scope=false."""
    from rag.embedding.indexer import read_frozen
    h("files: file chunk, sha256 so với FROZEN.md")
    chunk_dir = Path(CFG["chunks"]["c2"]).parent
    fz = read_frozen(chunk_dir / "FROZEN.md") if (chunk_dir / "FROZEN.md").exists() else {}
    files = {**{c: Path(p) for c, p in CFG["chunks"].items()}, "c3_parents": Path(CFG["c3_parents"])}
    last = {}  # sha256 + số dòng của lần index gần nhất (từ embedding_usage.jsonl)
    ulog = Path(CFG["usage_log"])
    for r in (jl(ulog) if ulog.exists() else []):
        if r.get("event") == "chunk_file":
            last[r["file"]] = (r["sha256"], r["n_rows"], r["at"])
    for name, p in files.items():
        rows = jl(p)
        s = sha(p)
        out = sum(1 for r in rows if (r.get("metadata") or {}).get("in_scope") is False)
        match = "KHỚP FROZEN" if fz.get(p.name) == s else ("LỆCH FROZEN" if p.name in fz else "không có trong FROZEN")
        li = last.get(p.name)
        idx = "chưa từng index" if li is None else ("ĐÃ INDEX đúng bản này" if li[0] == s else f"!! index lần cuối là bản KHÁC ({li[1]} dòng, sha {li[0][:12]}…, {li[2]}) -> cần index lại")
        print(f"  {name:11s} {len(rows):6d} dòng  in_scope=false: {out}  sha256={s[:12]}…  [{match}]  {idx}")
    ex = Path(chunk_dir / "excluded_chunks.jsonl")
    print(f"  excluded_chunks.jsonl: {len(jl(ex))} dòng (KHÔNG embed/index; indexer từ chối file này)")
    ids = {c: {r["chunk_id"] for r in jl(Path(p))} for c, p in CFG["chunks"].items() if c != "c2_novlm"}
    exid = {r["chunk_id"] for r in jl(ex)}
    print(f"  giao giữa chunk_id của c1/c2/c3 và excluded: {sum(len(v & exid) for v in ids.values())} (phải = 0)")
    print(f"  parents SQLite: ", end="")
    pp = Path(CFG["qdrant"]["parents_path"])
    print(sqlite3.connect(str(pp)).execute("select count(*) from parents").fetchone()[0] if pp.exists() else "không có file", "dòng")


# ------------------------------------------------------------------------------------------------ usage
def sec_usage() -> None:
    """Bảng 5: token, request, thời gian, chi phí; nhóm theo lần chạy (khoảng cách > 120 giây giữa hai request)."""
    import time
    h("usage: token và chi phí embedding")
    price = CFG["openai"]["price_per_1m_tokens"]["small"]
    recs = jl(Path(CFG["usage_log"]))
    api = [r for r in recs if "prompt_tokens" in r]
    ev = [r for r in recs if r.get("event")]
    ts = lambda r: time.mktime(time.strptime(r["at"], "%Y-%m-%dT%H:%M:%S"))
    groups: list[list[dict]] = []
    for r in api:
        if groups and ts(r) - ts(groups[-1][-1]) <= 120:
            groups[-1].append(r)
        else:
            groups.append([r])
    for i, g in enumerate(groups, 1):
        tk = sum(x["prompt_tokens"] or 0 for x in g)
        print(f"  nhóm {i}: {g[0]['at']} → {g[-1]['at']}  {len(g):3d} request  {sum(x['n_inputs'] for x in g):6d} text  {tk:9d} token  ≈ {tk / 1e6 * price:.4f} USD")
    tot = sum(r["prompt_tokens"] or 0 for r in api)
    print(f"  TỔNG: {len(api)} request, {sum(r['n_inputs'] for r in api)} text, {tot} token, ≈ {tot / 1e6 * price:.4f} USD (giá small {price} USD/1M token)")
    print(f"  sự kiện sha256 đã ghi: {Counter(r['event'] for r in ev)}")
    for r in ev:
        if r["event"] == "chunk_file":
            print(f"    {r['at']} chunk_file {r['config']:10s} {r['n_rows']:5d} dòng sha256={r['sha256'][:12]}…")
    cache = Path(CFG["cache_dir"]) / CFG["openai"]["models"]["small"]["name"] / "cache.sqlite"
    if cache.exists():
        print(f"  cache embedding small: {sqlite3.connect(str(cache)).execute('select count(*) from emb').fetchone()[0]} vector")


# ------------------------------------------------------------------------------------------------ bm25
def sec_bm25() -> None:
    h("bm25: avgdl từng collection và va chạm hash")
    st = json.loads(Path(CFG["bm25"]["stats_path"]).read_text(encoding="utf-8"))
    for k, v in st.items():
        if k.startswith("_"):
            print(f"  {k}: n_terms={v['n_terms']}  n_ids={v['n_ids']}  n_collisions={v['n_collisions']}")
        else:
            print(f"  {k:13s} n_docs={v['n_docs']:5d}  avgdl={v['avgdl']:.1f}  k1={v['k1']} b={v['b']}  {v.get('normalize', '')}")
    from rag.embedding import bm25
    sw = bm25.load_stopwords(CFG["bm25"]["stopwords"])
    for s in ("Lịch thi học kỳ I năm học 2025 - 2026", "Học phần AE321 (3 tín chỉ), phí 650.000 đồng, điểm 4,0", "Học phí học lại khóa 38 K39"):
        print(f"  tokenize({s!r}) = {bm25.tokenize(s, sw)}")
    print(f"  token_id('ae321') = {bm25.token_id('ae321')}")


# ------------------------------------------------------------------------------------------------ quick
def sec_quick() -> None:
    """Bảng 7, 9: hạng chunk đúng đầu tiên theo chế độ và tổng hạng 10 lượt (đọc data/eval/retrieval_quick_eval.json)."""
    h("quick: hạng chunk đúng đầu tiên (5 câu x không khóa/khóa 38)")
    p = EVAL_DIR / "retrieval_quick_eval.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    modes = ["dense", "bm25", "hybrid", "hybrid_rerank"]
    print(f"  {'câu':60s} {'ctx':8s} " + " ".join(f"{m:>13s}" for m in modes))
    sums = {m: 0 for m in modes}
    for r in d["table"]:
        print(f"  {r['q'][:58]:60s} {r['ctx']:8s} " + " ".join(f"{str(r['ranks'][m]):>13s}" for m in modes))
        for m in modes:
            sums[m] += r["ranks"][m] or 99
    print(f"  TỔNG HẠNG 10 lượt (thấp = tốt): {sums}")
    t = d["timings"]
    print("  thời gian mỗi bước (giây): " + ", ".join(f"{k}: tb {statistics.mean(v):.3f} max {max(v):.3f} (n={len(v)})" for k, v in t.items()))
    dups = d["duplicates"]
    print(f"  khử trùng lặp: {len(dups)} trường hợp, theo chế độ {dict(Counter(x['mode'] for x in dups))}")
    print("  file đầy đủ (kèm định nghĩa đáp án đúng): data/eval/retrieval_quick_eval.md")


# ------------------------------------------------------------------------------------------------ rerank
def sec_rerank() -> None:
    """Bảng 10-13: luồng/batch, ONNX so với torch, quét cấu hình, biến thể fused."""
    h("rerank: các số đo tối ưu reranker trên CPU")
    env = json.loads((BENCH / "env.json").read_text(encoding="utf-8"))
    print("  môi trường:", {k: env[k] for k in ("torch", "num_threads_default", "physical_cores", "logical_cores", "mkl", "onnxruntime")})
    th = json.loads((BENCH / "threads.json").read_text(encoding="utf-8"))
    print("  [Bảng 10] luồng/batch/inference_mode (torch fp32, 20 cặp x 5 câu):")
    for r in th["rows"]:
        print(f"    {r['cau_hinh']:50s} trung vị {r['median_s']:6.2f}s  tb {r['mean_s']:6.2f}s")
    cp = json.loads((BENCH / "compare.json").read_text(encoding="utf-8"))
    print("  [Bảng 11] ONNX int8 so với torch fp32:")
    for r in cp:
        print(f"    {r['q'][:50]:50s} spearman={r['spearman']}  top5_cùng_tập={r['top5_same_set']}  top5_cùng_thứ_tự={r['top5_same_order']}  lệch_logit={r['mean_abs_logit_diff']}")
    sw = json.loads((BENCH / "sweep.json").read_text(encoding="utf-8"))
    print("  [Bảng 12] quét cấu hình (trung vị 10 lượt):")
    for r in sw["rows"]:
        rk = " ".join(f"{k}:{v or '-'}" for k, v in r["ranks"].items())
        print(f"    {r['backend']:5s} max_length={r['max_length']} n_rerank={r['n_rerank']:2d}  trung vị {r['median_s']:6.2f}s | {rk}")
    fu = json.loads((BENCH / "fused.json").read_text(encoding="utf-8"))
    print("  [Bảng 13] tổng hạng 10 lượt theo biến thể (torch, n=20, max_length 512; thấp = tốt):")
    keys = [k for k in fu[0] if k not in ("backend", "q", "ctx")]
    for be in ("torch", "onnx"):
        rows = [r for r in fu if r["backend"] == be]
        print(f"    {be:5s} " + ", ".join(f"{k}={sum(r[k] or 99 for r in rows)}" for k in keys))


# ------------------------------------------------------------------------------------------------ live
def sec_live() -> None:
    """Cần Qdrant đang chạy: số điểm, in_scope=false, lọc khóa so với khoa_matches(), status, mẫu ngẫu nhiên."""
    from rag.embedding.indexer import _all_payloads, load_chunks, verify_filters
    from rag.embedding.qdrant_store import connect, verify_collection
    h("live: kiểm tra trực tiếp trên Qdrant")
    cl = connect(CFG["qdrant"]["url"])
    for c, name in CFG["qdrant"]["collections"].items():
        n_rows = len(load_chunks(CFG["chunks"][c]))
        v = verify_collection(cl, name, n_rows, "small")
        print(f"  {name:13s} điểm={v['points']:6d}  dòng_file={v['expected']:6d}  khớp={v['count_ok']}  in_scope=false={v['in_scope_false']}  mẫu_ngẫu_nhiên_ok={not v['problems']}")
        if c == "c2":
            for s in v["sample"]:
                print(f"      mẫu: {s['chunk_id'][-40:]:40s} payload_fields={s['n_payload_fields']} dim_dense={s['dim']} sparse_nnz={s['sparse_nnz']}")
    vf = verify_filters(cl, CFG["qdrant"]["collections"]["c2"])
    print(f"  verify_filters (lọc khóa so với khoa_matches, status): ok={vf['ok']} lỗi={vf['errors']}")
    for k in (37, 38, 39):
        r = vf["report"][k]
        print(f"    K={k}: {r['count']} điểm; cặp (khoa_tu,khoa_den)={r['cap_khoa']}")
    print(f"    điểm hieu_luc & in_scope: {vf['report']['n_points_hieu_luc_in_scope']}")
    print("    văn bản het_hieu_luc bị loại:")
    for d, t in vf["report"]["het_hieu_luc_bi_loai"]:
        print(f"      {d}  {t}")
    pts = _all_payloads(cl, CFG["qdrant"]["collections"]["c2"])
    qc = Counter((p["doc_id"][-8:], p["status"], p["khoa_tu"], p["khoa_den"]) for p in pts if "Quy chế đào tạo" in (p["title"] or ""))
    print("    các bản Quy chế đào tạo (doc, status, khoa_tu, khoa_den): ", dict(qc))


SECTIONS = {"files": sec_files, "usage": sec_usage, "bm25": sec_bm25, "quick": sec_quick, "rerank": sec_rerank, "live": sec_live}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", nargs="+", choices=list(SECTIONS), help="chỉ in các mục này")
    ap.add_argument("--live", action="store_true", help="thêm mục live (cần Qdrant)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    todo = a.section or [s for s in SECTIONS if s != "live"] + (["live"] if a.live else [])
    for s in todo:
        SECTIONS[s]()

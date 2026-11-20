"""Điều phối: đọc chunk jsonl -> embed (cache) -> BM25 sparse -> upsert Qdrant -> đồng bộ -> kiểm tra.

Mặc định chỉ DRY-RUN (không gọi API, không đụng Qdrant); `yes=True` mới gọi API và ghi Qdrant.
excluded_chunks.jsonl bị TỪ CHỐI ở `load_chunks` (đường dẫn hoặc chunk in_scope=false).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from qdrant_client import models

from rag.embedding.settings import embedding_config
from rag.embedding import bm25
from rag.embedding.openai_embedder import OpenAIEmbedder, OverBudget, QuotaExhausted
from rag.embedding.qdrant_store import (DENSE, SPARSE, connect, ensure_collection, load_parents, make_payload, point_id,
                                        sync_delete_stale_ids, upsert_points, verify_collection)

ORDER = ["c2", "c1", "c3", "c2_novlm"]  # thứ tự chạy khi --config all


class ChunkFileChanged(RuntimeError):
    """File chunk bị đổi (sha256 khác) trong lúc đang chạy."""


def load_chunks_sha(path: Path) -> tuple[list[dict], str]:
    """Đọc file chunk ĐÚNG MỘT LẦN (bytes) -> (các dòng, sha256 của file)."""
    path = Path(path)
    if "excluded" in path.name.lower():
        raise ValueError(f"Từ chối {path.name}: chunk bị loại (danh sách sinh viên, ngoài phạm vi) KHÔNG được embed/index")
    raw = path.read_bytes()
    rows = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    ids = [r["chunk_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: chunk_id trùng")
    bad = [r["chunk_id"] for r in rows if r["metadata"].get("in_scope") is False]
    if bad:
        raise ValueError(f"{path.name}: có {len(bad)} chunk in_scope=false (ví dụ {bad[0]}); không được index")
    return rows, hashlib.sha256(raw).hexdigest()


def load_chunks(path: Path) -> list[dict]:
    return load_chunks_sha(path)[0]


def check_unchanged(path: Path, sha: str) -> None:
    """Tính lại sha256 (chỉ băm, không parse); khác lúc đầu -> dừng."""
    now = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if now != sha:
        raise ChunkFileChanged(f"{Path(path).name} đã thay đổi trong lúc chạy (sha256 {sha[:12]}… -> {now[:12]}…). Dừng; chạy lại sau khi chunking ổn định.")


def log_file_sha(cfg: dict, config: str, path: Path, sha: str, n_rows: int) -> None:
    p = Path(cfg["usage_log"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "chunk_file", "config": config, "file": Path(path).name,
                            "sha256": sha, "n_rows": n_rows}, ensure_ascii=False) + chr(10))


FROZEN_NAME = "FROZEN.md"


def read_frozen(path: Path) -> dict[str, str]:
    """Đọc FROZEN.md: mọi dòng có tên file *.jsonl và một chuỗi hex 64 ký tự -> {tên file: sha256}."""
    import re
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m, h = re.search(r"([\w.\-]+\.jsonl)", line), re.search(r"\b([0-9a-fA-F]{64})\b", line)
        if m and h:
            out[m.group(1)] = h.group(1).lower()
    return out


def check_frozen(cfg: dict, frozen_path: Path, shas: dict[str, str]) -> dict[str, str]:
    """shas: {tên file: sha256 vừa tính}. Thiếu FROZEN.md, thiếu mục, hoặc lệch -> SystemExit. Ghi sha của FROZEN vào usage log."""
    if not Path(frozen_path).exists():
        raise SystemExit(f"File chunk không khớp FROZEN.md: không có {frozen_path} (chunking chưa đóng băng). "
                         f"Dùng --no-frozen-check để chạy thử.")
    fz = read_frozen(frozen_path)
    bad = [f"{n}: {'không có trong FROZEN.md' if n not in fz else 'sha256 ' + s[:12] + '… != FROZEN ' + fz[n][:12] + '…'}"
           for n, s in shas.items() if fz.get(n) != s]
    if bad:
        raise SystemExit("File chunk không khớp FROZEN.md:\n  " + "\n  ".join(bad))
    p = Path(cfg["usage_log"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for n in shas:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "frozen", "file": n, "sha256": fz[n]},
                               ensure_ascii=False) + chr(10))
    return fz


def resolve(config: str) -> list[str]:
    return ORDER if config == "all" else [config]


def dry_run(cfg: dict, configs: list[str], model: str, embedder: OpenAIEmbedder | None = None) -> dict:
    """In số chunk / chưa cache / token / chi phí cho từng cấu hình (chunk dùng chung text với cấu hình trước chỉ tính một lần)."""
    emb = embedder or OpenAIEmbedder(cfg, model)
    seen: set[str] = set()
    tot = {"tokens": 0, "n_missing": 0, "cost": 0.0, "has_price": emb.price is not None}
    print(f"[DRY-RUN] mô hình {emb.name}; cache {emb.cache.db.execute('select count(*) from emb').fetchone()[0]} vector")
    for c in configs:
        rows = load_chunks(cfg["chunks"][c])
        p = emb.plan([r["embed_text"] for r in rows], assume_done=seen)
        seen |= p["_keys"]
        cost = "chưa điền giá (price_per_1m_tokens)" if p["cost_usd"] is None else f"{p['cost_usd']:.4f} USD"
        print(f"  {c:9s} chunk={p['n_chunks']:5d}  text duy nhất={p['n_unique']:5d}  đã cache/trùng cấu hình trước={p['n_cached']:5d}  "
              f"chưa có={p['n_missing']:5d}  token cần gọi={p['tokens']:9d}  chi phí={cost}")
        tot["tokens"] += p["tokens"]
        tot["n_missing"] += p["n_missing"]
        tot["cost"] += p["cost_usd"] or 0.0
    tail = f"{tot['cost']:.4f} USD" if tot["has_price"] else "chưa điền giá"
    print(f"  TỔNG      chưa có={tot['n_missing']}  token cần gọi={tot['tokens']}  chi phí={tail}  (trần max_cost_usd={emb.max_cost})")
    return tot


def _bm25_pass(cfg: dict, rows: list[dict], name: str, tracker: bm25.CollisionTracker) -> tuple[list[list[str]], float]:
    sw = bm25.load_stopwords(cfg["bm25"]["stopwords"])
    toks = [bm25.tokenize(r["embed_text"], sw) for r in rows]
    for t in toks:
        tracker.add(t)
    avgdl = sum(len(t) for t in toks) / max(1, len(toks))
    return toks, avgdl


def _save_stats(cfg: dict, name: str, entry: dict) -> None:
    p = Path(cfg["bm25"]["stats_path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cur[name] = entry
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def index_config(cfg: dict, config: str, model: str, embedder: OpenAIEmbedder, client, tracker: bm25.CollisionTracker,
                 rows: list[dict], sha: str, parents_raw: bytes | None = None, progress=print) -> dict:
    """Embed phần thiếu, dựng điểm (dense của mô hình đang chạy + dense của mô hình kia nếu ĐÃ có sẵn trong cache + bm25), upsert, đồng bộ."""
    name = cfg["qdrant"]["collections"][config]
    texts = [r["embed_text"] for r in rows]
    plan = embedder.plan(texts)
    progress(f"[{config}] {plan['n_unique']} text duy nhất, {plan['n_missing']} chưa cache ({plan['tokens']} token)")
    emb_res = embedder.embed_missing(plan, progress) if plan["n_missing"] else {"embedded": 0, "prompt_tokens": 0}
    check_unchanged(cfg["chunks"][config], sha)  # file chunk không đổi trong lúc embed
    vecs = embedder.get_vectors(texts)
    other = "large" if model == "small" else "small"
    other_vecs = None
    if cfg["openai"]["models"].get(other):
        oe = OpenAIEmbedder(cfg, other, client=embedder._client)
        got = oe.get_vectors(texts, missing_ok=True)
        other_vecs = got if all(v is not None for v in got) else None  # chỉ giữ vector mô hình kia khi đủ bộ, tránh upsert làm mất
        oe.cache.close()
    toks, avgdl = _bm25_pass(cfg, rows, name, tracker)
    k1, b = cfg["bm25"]["k1"], cfg["bm25"]["b"]
    created = ensure_collection(client, name)
    points = []
    for i, r in enumerate(rows):
        idx, val = bm25.doc_to_sparse(toks[i], avgdl, k1, b)
        vec = {DENSE[model][0]: vecs[i].tolist(), SPARSE: models.SparseVector(indices=idx, values=val)}
        if other_vecs is not None:
            vec[DENSE[other][0]] = other_vecs[i].tolist()
        points.append(models.PointStruct(id=point_id(r["chunk_id"]), vector=vec, payload=make_payload(r)))
    check_unchanged(cfg["chunks"][config], sha)
    upsert_points(client, name, points, cfg["qdrant"].get("upsert_batch", 256))
    stale = sync_delete_stale_ids(client, name, {p.id for p in points})
    deleted = len(stale)
    progress(f"[{config}] upsert {len(points)} điểm vào {name}; xóa {deleted} điểm thừa"
             + (f": {stale[:50]}{' …' if deleted > 50 else ''}" if stale else ""))
    _save_stats(cfg, name, {"avgdl": avgdl, "n_docs": len(rows), "k1": k1, "b": b, "stopwords": str(Path(cfg["bm25"]["stopwords"]).name)})
    res = {"config": config, "collection": name, "created": created, "points": len(points), "deleted": deleted,
           "stale_chunk_ids": stale, "n_text_from_cache": plan["n_unique"] - plan["n_missing"],
           "n_text_api": plan["n_missing"], "embedded": emb_res["embedded"], "prompt_tokens": emb_res["prompt_tokens"], "avgdl": avgdl}
    if config == "c3":
        raw = parents_raw if parents_raw is not None else Path(cfg["c3_parents"]).read_bytes()
        res["parents"] = load_parents(cfg["qdrant"]["parents_path"], [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()])
        progress(f"[c3] parents sqlite: {res['parents']}")
    return res


def run_index(config: str, model: str, yes: bool, frozen_check: bool = True, cfg: dict | None = None, embedder: OpenAIEmbedder | None = None, client=None,
              progress=print) -> dict:
    cfg = cfg or embedding_config()
    configs = resolve(config)
    emb = embedder or OpenAIEmbedder(cfg, model)
    if not yes:
        out = dry_run(cfg, configs, model, emb)
        print("Chưa gọi API/Qdrant. Thêm --yes để chạy thật.")
        return {"dry_run": True, **out}
    t0 = time.time()
    client = client or connect(cfg["qdrant"]["url"])
    tracker = bm25.CollisionTracker()
    results, checks = [], []
    src = {c: load_chunks_sha(cfg["chunks"][c]) for c in configs}  # mỗi file chunk đọc đúng 1 lần
    parents_raw = Path(cfg["c3_parents"]).read_bytes() if "c3" in configs else None
    if frozen_check:
        shas = {Path(cfg["chunks"][c]).name: src[c][1] for c in configs}
        if parents_raw is not None:
            shas[Path(cfg["c3_parents"]).name] = hashlib.sha256(parents_raw).hexdigest()
        check_frozen(cfg, Path(cfg["chunks"]["c2"]).parent / FROZEN_NAME, shas)
        progress("FROZEN.md khớp sha256 của các file chunk cần index")
    if parents_raw is not None:
        log_file_sha(cfg, "c3_parents", cfg["c3_parents"], hashlib.sha256(parents_raw).hexdigest(), parents_raw.count(10))
    for c in configs:
        log_file_sha(cfg, c, cfg["chunks"][c], src[c][1], len(src[c][0]))
    try:
        for c in configs:
            rows, sha = src[c]
            results.append(index_config(cfg, c, model, emb, client, tracker, rows, sha, parents_raw, progress))
            check_unchanged(cfg["chunks"][c], sha)
            v = verify_collection(client, cfg["qdrant"]["collections"][c], len(rows), model)
            checks.append(v)
            progress(f"[{c}] kiểm tra: {'ĐẠT' if v['ok'] else 'CÓ VẤN ĐỀ'} — {v['points']}/{v['expected']} điểm, in_scope=false: {v['in_scope_false']}")
    except QuotaExhausted:
        raise SystemExit(f"Dừng do hết quota. Chạy tiếp: python scripts/ingest.py --stage index --config {config} --model {model} --yes")
    except ChunkFileChanged as e:
        raise SystemExit(f"LỖI: {e}")
    except OverBudget as e:
        raise SystemExit(f"Dừng, chưa gọi API: {e}")
    if "c2" in configs:
        vf = verify_filters(client, cfg["qdrant"]["collections"]["c2"])
        checks.append({"filters": vf})
        progress(f"[c2] lọc khóa/status: {'ĐẠT' if vf['ok'] else 'LỖI ' + str(vf['errors'])}")
        progress(json.dumps(vf["report"], ensure_ascii=False, indent=1, default=str))
    col = tracker.report()
    p = Path(cfg["bm25"]["stats_path"])
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    st["_hash_collisions"] = col
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    progress(f"BM25: {col['n_terms']} term duy nhất, {col['n_collisions']} va chạm hash")
    tot = {"n_text_from_cache": sum(r["n_text_from_cache"] for r in results), "n_text_api": sum(r["n_text_api"] for r in results),
           "prompt_tokens": sum(r["prompt_tokens"] for r in results)}
    progress(f"Tổng lần này: {tot['n_text_from_cache']} text từ cache, {tot['n_text_api']} text gọi API, {tot['prompt_tokens']} token")
    return {"dry_run": False, "totals": tot, "results": results, "checks": checks, "hash_collisions": col, "seconds": round(time.time() - t0, 1)}


def run_sparse_only(config: str, yes: bool, frozen_check: bool = True, cfg: dict | None = None, client=None, progress=print) -> dict:
    """Chỉ tính lại và cập nhật vector sparse `bm25` (chuẩn hóa miền mới); GIỮ NGUYÊN dense; KHÔNG gọi OpenAI. Kiểm tra FROZEN như index."""
    cfg = cfg or embedding_config()
    configs = resolve(config)
    src = {c: load_chunks_sha(cfg["chunks"][c]) for c in configs}  # mỗi file chunk đọc đúng 1 lần
    if frozen_check:
        check_frozen(cfg, Path(cfg["chunks"]["c2"]).parent / FROZEN_NAME, {Path(cfg["chunks"][c]).name: src[c][1] for c in configs})
        progress("FROZEN.md khớp sha256 của các file chunk")
    if not yes:
        for c in configs:
            progress(f"[DRY-RUN sparse-only] {c}: sẽ cập nhật bm25 cho {len(src[c][0])} điểm trong {cfg['qdrant']['collections'][c]} (0 token OpenAI)")
        print("Chưa ghi gì. Thêm --yes để chạy thật.")
        return {"dry_run": True}
    client = client or connect(cfg["qdrant"]["url"])
    tracker = bm25.CollisionTracker()
    k1, b = cfg["bm25"]["k1"], cfg["bm25"]["b"]
    out = []
    for c in configs:
        rows, sha = src[c]
        name = cfg["qdrant"]["collections"][c]
        n_before = client.count(name, exact=True).count
        if n_before != len(rows):
            raise SystemExit(f"{name}: {n_before} điểm != {len(rows)} dòng file chunk; chạy index đầy đủ trước (sparse-only chỉ cập nhật điểm đã có)")
        toks, avgdl = _bm25_pass(cfg, rows, name, tracker)
        pts = []
        for i, r in enumerate(rows):
            idx, val = bm25.doc_to_sparse(toks[i], avgdl, k1, b)
            pts.append(models.PointVectors(id=point_id(r["chunk_id"]), vector={SPARSE: models.SparseVector(indices=idx, values=val)}))
        for i in range(0, len(pts), cfg["qdrant"].get("upsert_batch", 256)):
            client.update_vectors(name, points=pts[i:i + cfg["qdrant"].get("upsert_batch", 256)], wait=True)
        check_unchanged(cfg["chunks"][c], sha)
        _save_stats(cfg, name, {"avgdl": avgdl, "n_docs": len(rows), "k1": k1, "b": b, "stopwords": Path(cfg["bm25"]["stopwords"]).name,
                                "normalize": "domain_v1 (hk*, nh_*, khoa_*)"})
        v = verify_collection(client, name, len(rows), "small")  # dense_small vẫn đủ chiều + sparse không rỗng
        progress(f"[{c}] sparse-only: {len(pts)} điểm, avgdl={avgdl:.1f}; kiểm tra {'ĐẠT' if v['ok'] else 'CÓ VẤN ĐỀ'}")
        out.append({"config": c, "points": len(pts), "avgdl": avgdl, "verify_ok": v["ok"]})
    col = tracker.report()
    p = Path(cfg["bm25"]["stats_path"])
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    st["_hash_collisions"] = col
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    progress(f"BM25: {col['n_terms']} term duy nhất, {col['n_collisions']} va chạm hash")
    return {"dry_run": False, "results": out, "hash_collisions": col}


SMOKE_QUERIES = ["Sinh viên được đăng ký tối đa bao nhiêu tín chỉ một học kỳ?", "Học phí học lại khóa 38 là bao nhiêu?",
                 "Học phần AE321 bao nhiêu tín chỉ?", "Điều kiện để chuyển ngành là gì?", "Lịch thi học kỳ I năm học 2025 - 2026"]


def _all_payloads(client, name: str) -> list[dict]:
    out, off = [], None
    while True:
        recs, off = client.scroll(name, limit=1000, offset=off, with_payload=["chunk_id", "doc_id", "title", "status", "in_scope", "khoa_tu", "khoa_den"],
                                  with_vectors=False)
        out += [r.payload | {"_id": str(r.id)} for r in recs]
        if off is None:
            return out


def verify_filters(client, name: str, ks=(37, 38, 39)) -> dict:
    """Trên server thật: (1) lọc khóa bằng IsNullCondition so với khoa_matches() trên cùng tập điểm (lệch 1 điểm = lỗi);
    (2) lọc status=hieu_luc loại hết văn bản het_hieu_luc."""
    from rag.chunking.metadata import khoa_matches
    from rag.embedding.qdrant_store import build_filter
    pts = _all_payloads(client, name)
    errors, report = [], {}
    for k in ks:
        flt = build_filter(status=None, in_scope=None, khoa=k)
        got, off = set(), None
        while True:
            recs, off = client.scroll(name, scroll_filter=flt, limit=1000, offset=off, with_payload=False, with_vectors=False)
            got |= {str(r.id) for r in recs}
            if off is None:
                break
        exp = {p["_id"] for p in pts if khoa_matches(p["khoa_tu"], p["khoa_den"], k)}
        if got != exp:
            errors.append(f"K={k}: server {len(got)} điểm != khoa_matches {len(exp)} (thừa {len(got - exp)}, thiếu {len(exp - got)})")
        n_count = client.count(name, exact=True, count_filter=flt).count
        sel = [p for p in pts if p["_id"] in got]
        titles = sorted({p["title"] for p in sel if p["title"]})
        pairs = sorted({(p["khoa_tu"], p["khoa_den"]) for p in sel}, key=str)
        nn = [p for p in pts if p["khoa_tu"] is None and p["khoa_den"] is None]
        if any(p["_id"] not in got for p in nn):
            errors.append(f"K={k}: có tài liệu khoa_tu=null & khoa_den=null không khớp")
        report[k] = {"count": n_count, "cap_khoa": pairs, "tieu_de_mau": titles[:2],
                     "tieu_de_quy_che": [x for x in titles if "Quy chế đào tạo" in x or "quy chế đào tạo" in x.lower()][:5]}
    hl = client.scroll(name, scroll_filter=build_filter("hieu_luc", True), limit=100000, with_payload=["doc_id", "status"], with_vectors=False)[0]
    het = sorted({(p["doc_id"], p["title"]) for p in pts if p["status"] != "hieu_luc"}, key=str)
    leak = [p for p in hl if p.payload["status"] != "hieu_luc"]
    if leak:
        errors.append(f"status=hieu_luc vẫn lọt {len(leak)} điểm het_hieu_luc")
    report["het_hieu_luc_bi_loai"] = het
    report["n_points_hieu_luc_in_scope"] = len(hl)
    return {"ok": not errors, "errors": errors, "report": report}


def smoke(model: str = "small", config: str = "c2", top: int = 5, cfg: dict | None = None, embedder: OpenAIEmbedder | None = None,
          client=None) -> None:
    """Smoke test (KHÔNG phải đánh giá): top-5 bằng dense và bằng BM25 riêng, lọc status=hieu_luc, in_scope=true. Embed 5 câu hỏi (rất rẻ)."""
    from rag.embedding.qdrant_store import build_filter
    cfg = cfg or embedding_config()
    emb = embedder or OpenAIEmbedder(cfg, model)
    client = client or connect(cfg["qdrant"]["url"])
    name = cfg["qdrant"]["collections"][config]
    flt = build_filter("hieu_luc", True)
    plan = emb.plan(SMOKE_QUERIES)
    if plan["n_missing"]:
        emb.embed_missing(plan)
    qvecs = emb.get_vectors(SMOKE_QUERIES)

    def short(p):
        bc = p.payload["embed_text"].split("]")[0].lstrip("[") if p.payload["embed_text"].startswith("[") else p.payload["embed_text"][:80]
        kh = f"[{p.payload.get('khoa_tu')}-{p.payload.get('khoa_den')}]"
        return f"{p.payload['chunk_id'][-34:]:34s} {p.score:7.4f} {kh:9s} {bc[:80]}"
    for q, v in zip(SMOKE_QUERIES, qvecs):
        for khoa in (None, 38):  # hai chế độ: không lọc khóa, và lọc K=38
            flt = build_filter("hieu_luc", True, khoa=khoa)
            print(f"\n### {q}   [{'không lọc khóa' if khoa is None else 'lọc K=38'}]")
            print("  -- dense")
            for p in client.query_points(name, query=v.tolist(), using=DENSE[model][0], query_filter=flt, limit=top, with_payload=True).points:
                print("  ", short(p))
            print("  -- BM25")
            for p in client.query_points(name, query=bm25.query_to_sparse(q), using=SPARSE, query_filter=flt, limit=top, with_payload=True).points:
                print("  ", short(p))

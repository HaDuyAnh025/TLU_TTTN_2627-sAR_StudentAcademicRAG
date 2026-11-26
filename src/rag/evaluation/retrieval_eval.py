"""Bộ chấm retrieval theo SPAN đáp án (không theo chunk_id) => so sánh được C1/C2/C3.

Quy ước chấm (ghi lại trong summary.md của mỗi lần chạy):
  - Chunk "phủ" span khi cùng doc_id và (ký tự giao nhau) / (độ dài span) >= `cover_thr` (mặc định 0.5). Chunk bảng dùng vùng ký tự của các dòng gốc.
  - Recall@k = tỉ lệ span của câu có chunk phủ nằm trong top-k (hạng cuối của chế độ, sau khử trùng lặp).
  - MRR = 1 / hạng của chunk đầu tiên phủ MỘT span bất kỳ của câu (0 nếu không có trong danh sách xếp hạng).
  - Recall@budget = tỉ lệ span được phủ >= cover_thr bởi HỢP các mục context đã ghép theo context_budget_tokens (cố định cho mọi cấu hình).
    C3: mục = parent. Mục bị cắt theo token được ước lượng vùng phủ theo tỉ lệ độ dài chữ còn lại.
  - c2_novlm: tọa độ ký tự của chunk KHÔNG khớp văn bản tài liệu (bản không VLM có văn bản khác) => chấm theo VĂN BẢN:
    phủ = tỉ lệ token nội dung của span có trong chunk. Để so công bằng, c2 cũng được chấm theo văn bản trên cùng nhóm câu (nhãn "c2(text)").
Hàm ở đây không cần mạng/Qdrant (trừ `run_grid`, nhận Retriever từ bên ngoài) nên kiểm thử được.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from rag.config import ROOT, load_config
from rag.evaluation import testset as T

CHUNK_FILES = {"c1": "c1_chunks.jsonl", "c2": "c2_chunks.jsonl", "c3": "c3_chunks.jsonl", "c2_novlm": "c2_novlm_chunks.jsonl"}
MODES = ("dense", "bm25", "hybrid", "hybrid_rerank", "hybrid_rerank_fused")
RERANK_MODES = ("hybrid_rerank", "hybrid_rerank_fused")
KS = (1, 3, 5)


# ------------------------------------------------------------------ cổng kiểm tra index
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_frozen(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m, h = re.search(r"([\w.\-]+\.jsonl)", line), re.search(r"\b([0-9a-fA-F]{64})\b", line)
        if m and h:
            out[m.group(1)] = h.group(1).lower()
    return out


def last_indexed_shas(usage_log: Path) -> dict[str, str]:
    """sha256 của từng file chunk trong lần index GẦN NHẤT (sự kiện chunk_file cuối cùng của mỗi file)."""
    out: dict[str, str] = {}
    p = Path(usage_log)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("event") == "chunk_file":
            out[r["file"]] = r["sha256"]
    return out


def check_index_gate(frozen_path: Path, usage_log: Path, chunks_dir: Path, files=CHUNK_FILES.values(), verify_files: bool = True) -> dict:
    """So sha256 trong FROZEN.md với sha ghi trong embedding_usage.jsonl của lần index gần nhất (và với file chunk thật). Lệch => SystemExit."""
    if not Path(frozen_path).exists():
        raise SystemExit(f"Dừng: không có {frozen_path}")
    fz, idx = read_frozen(frozen_path), last_indexed_shas(usage_log)
    bad = []
    for f in files:
        if f not in fz:
            bad.append(f"{f}: không có trong FROZEN.md")
        elif f not in idx:
            bad.append(f"{f}: chưa có bản ghi index trong embedding_usage.jsonl")
        elif fz[f] != idx[f]:
            bad.append(f"{f}: FROZEN {fz[f][:12]}… != đã index {idx[f][:12]}… (Qdrant chưa index lại theo FROZEN mới)")
        elif verify_files and (Path(chunks_dir) / f).exists() and sha256_file(Path(chunks_dir) / f) != fz[f]:
            bad.append(f"{f}: file chunk trên đĩa lệch FROZEN.md")
    if bad:
        raise SystemExit("Dừng, KHÔNG chấm: index không khớp FROZEN.md:\n  " + "\n  ".join(bad))
    return {"frozen": {f: fz[f] for f in files if f in fz}, "indexed": {f: idx[f] for f in files if f in idx}}


# ------------------------------------------------------------------ chỉ mục chunk (tọa độ + nội dung)
class ChunkIndex:
    """chunk_id -> (doc_id, char_start, char_end, len(embed_text), content|None); parent_id -> (doc_id, cs, ce) cho C3."""

    def __init__(self) -> None:
        self.chunks: dict[str, dict] = {}
        self.parents: dict[str, dict] = {}

    @classmethod
    def load(cls, chunk_path: Path, parents_path: Path | None = None, with_content: bool = False) -> "ChunkIndex":
        ix = cls()
        with Path(chunk_path).open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                m = r["metadata"]
                ix.chunks[r["chunk_id"]] = {"doc_id": m["doc_id"], "cs": m.get("char_start"), "ce": m.get("char_end"), "elen": len(r["embed_text"]),
                                            "parent": m.get("parent_id"), "content": r["content"] if with_content else None}
        if parents_path and Path(parents_path).exists():
            with Path(parents_path).open(encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    m = r["metadata"]
                    ix.parents[r["parent_id"]] = {"doc_id": m["doc_id"], "cs": m.get("char_start"), "ce": m.get("char_end"), "elen": len(r["embed_text"]),
                                                  "content": r["content"] if with_content else None}
        return ix


# ------------------------------------------------------------------ độ phủ
_TOK = re.compile(r"\w+", re.U)


def content_tokens(s: str) -> set[str]:
    sw = T._stopwords()
    return {t for t in _TOK.findall(T.nfc(s).lower()) if t not in sw and (len(t) > 1 or t.isdigit())}


def text_coverage(chunk_text: str, span_text: str) -> float:
    """Tỉ lệ token nội dung của span có trong chunk (dùng cho c2_novlm, nơi không so được tọa độ)."""
    st = content_tokens(span_text)
    return len(st & content_tokens(chunk_text)) / len(st) if st else 0.0


def chunk_cover(rec: dict, span: dict, mode: str) -> float:
    if rec["doc_id"] != span["doc_id"]:
        return 0.0
    if mode == "text":
        return text_coverage(rec["content"] or "", span["quote"])
    if rec["cs"] is None or rec["ce"] is None:
        return 0.0
    return T.span_coverage((rec["cs"], rec["ce"]), (span["char_start"], span["char_end"]))


def item_interval(item: dict, ix: ChunkIndex) -> tuple[str, int, int, str | None] | None:
    """(doc_id, cs, ce, text) của một mục context; mục C3 parent dùng khoảng của parent; mục bị cắt thì thu hẹp theo tỉ lệ chữ."""
    if item.get("parent") and item["id"] in ix.parents:
        rec = ix.parents[item["id"]]
    else:
        rec = ix.chunks.get(item["id"])
    if not rec or rec["cs"] is None:
        return None
    cs, ce = rec["cs"], rec["ce"]
    if item.get("truncated") and rec.get("elen"):
        frac = max(0.0, min(1.0, len(item.get("text") or "") / rec["elen"]))
        ce = cs + int((ce - cs) * frac)
    return rec["doc_id"], cs, ce, item.get("text")


def score_question(q: dict, ranked_ids: list[str], ctx_items: list[dict], ix: ChunkIndex, thr: float = 0.5, cov_mode: str = "char", ks=KS) -> dict:
    """Chỉ số của MỘT câu cho MỘT (cấu hình, chế độ). q["expected"] là các span; ranked_ids là hạng cuối (chunk_id)."""
    spans = q["expected"]
    n = len(spans)
    cov = [[chunk_cover(ix.chunks[c], s, cov_mode) if c in ix.chunks else 0.0 for s in spans] for c in ranked_ids]  # [rank][span]
    hit_rank = next((i + 1 for i, row in enumerate(cov) if any(v >= thr for v in row)), None)
    out = {"mrr": 1.0 / hit_rank if hit_rank else 0.0, "first_hit_rank": hit_rank}
    for k in ks:
        out[f"recall@{k}"] = sum(1 for j in range(n) if any(cov[i][j] >= thr for i in range(min(k, len(cov))))) / n
    # budget: hợp các mục context
    if cov_mode == "text":
        ctx_text = "\n".join((it.get("text") or "") for it in ctx_items)
        got = sum(1 for s in spans if text_coverage(ctx_text, s["quote"]) >= thr)
    else:
        by_doc: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for it in ctx_items:
            iv = item_interval(it, ix)
            if iv:
                by_doc[iv[0]].append((iv[1], iv[2]))
        got = sum(1 for s in spans if T.union_coverage(by_doc.get(s["doc_id"], []), (s["char_start"], s["char_end"])) >= thr)
    out["recall@budget"] = got / n
    return out


def wrong_version_top1(q: dict, ranked_doc_ids: list[str], version_docs: set[str]) -> bool | None:
    """Câu phụ thuộc khóa: chunk hạng 1 thuộc một phiên bản Quy chế KHÁC phiên bản kỳ vọng."""
    exp = {e["doc_id"] for e in q["expected"]}
    if not ranked_doc_ids or not (exp & version_docs):
        return None
    top = ranked_doc_ids[0]
    return top in version_docs and top not in exp


# ------------------------------------------------------------------ ngưỡng từ chối
def threshold_curve(pos: list[float], neg: list[float]) -> list[dict]:
    """pos = điểm cao nhất của câu CÓ đáp án; neg = của câu ngoài phạm vi. Quy tắc: từ chối khi điểm < t.
    refuse_correct = tỉ lệ câu ngoài phạm vi bị từ chối đúng; refuse_wrong = tỉ lệ câu có đáp án bị từ chối nhầm."""
    vals = sorted({round(v, 6) for v in pos + neg})
    if not vals:
        return []
    ts = [vals[0] - 1e-6] + [(a + b) / 2 for a, b in zip(vals, vals[1:])] + [vals[-1] + 1e-6]
    rows = []
    for t in ts:
        rc = sum(1 for v in neg if v < t) / len(neg) if neg else None
        rw = sum(1 for v in pos if v < t) / len(pos) if pos else None
        rows.append({"threshold": round(t, 6), "refuse_correct": rc, "refuse_wrong": rw,
                     "youden": (rc - rw) if rc is not None and rw is not None else None})
    return rows


def pick_threshold(curve: list[dict], max_wrong: float = 0.05) -> dict | None:
    """Trên dev: ngưỡng có refuse_correct lớn nhất với refuse_wrong <= max_wrong (hòa: ngưỡng thấp hơn)."""
    ok = [r for r in curve if r["refuse_wrong"] is not None and r["refuse_correct"] is not None and r["refuse_wrong"] <= max_wrong]
    return max(ok, key=lambda r: (r["refuse_correct"], -r["threshold"])) if ok else None


# ------------------------------------------------------------------ tổng hợp
def _mean(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 4) if v else None


def _pct(v: list[float], p: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(p * len(s)))], 4)


METRICS = ("recall@1", "recall@3", "recall@5", "mrr", "recall@budget")


def aggregate(per_q: list[dict]) -> list[dict]:
    """per_q: bản ghi per_question (đã có label, mode, doc_type, type, metrics, timings). Trả dòng summary theo (label, mode, kind, group)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in per_q:
        if r.get("scored") is False:
            continue
        keys = [("all", "all"), ("doc_type", r["doc_type"]), ("type", r["type"])]
        if r.get("tags"):
            keys += [("tag", t) for t in r["tags"]]
        for kind, g in keys:
            groups[(r["label"], r["mode"], kind, g)].append(r)
    out = []
    for (label, mode, kind, g), rs in sorted(groups.items()):
        row = {"label": label, "mode": mode, "kind": kind, "group": g, "n": len(rs)}
        for m in METRICS:
            row[m] = _mean([r["metrics"][m] for r in rs])
        tot = [sum(r["timings"].values()) for r in rs]
        row["latency_mean_s"], row["latency_p50_s"], row["latency_p95_s"] = _mean(tot), _pct(tot, 0.5), _pct(tot, 0.95)
        out.append(row)
    return out


def step_latency(per_q: list[dict]) -> list[dict]:
    acc: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in per_q:
        for step, v in r["timings"].items():
            acc[(r["label"], r["mode"])][step].append(v)
    return [{"label": l, "mode": m, **{f"{s}_mean": _mean(v) for s, v in sorted(st.items())}} for (l, m), st in sorted(acc.items())]


def write_csv(path: Path, rows: list[dict]) -> None:
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def fmt(v) -> str:
    return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def md_table(rows: list[dict], cols: list[str], head: list[str] | None = None) -> list[str]:
    head = head or cols
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(fmt(r.get(c)) for c in cols) + " |" for r in rows]
    return out


def summary_md(run: dict, summ: list[dict], lat: list[dict], extra: dict) -> str:
    L = [f"# Kết quả đánh giá retrieval — run `{run['run_id']}`", "",
         f"- split: **{run['split']}** ({run['n_questions']} câu có đáp án, {run['n_oos']} câu ngoài phạm vi); cover_thr={run['cover_thr']}",
         f"- FROZEN.md sha256: `{run['frozen_sha'][:16]}…`; questions.jsonl sha256: `{run['questions_sha'][:16]}…`",
         f"- reranker nhanh: {run['rerank_fast']}; đối chiếu: {run['rerank_ref']}",
         "- Quy ước chấm: xem docstring `rag/evaluation/retrieval_eval.py` (phủ span >= ngưỡng; Recall@budget = hợp context ghép theo ngân sách token; c2_novlm chấm theo văn bản).",
         "- **Không chỉnh tham số trên tập test.** " + ("Run này trên DEV." if run["split"] == "dev" else "Run này trên TEST (báo cáo cuối)."), ""]
    allr = [r for r in summ if r["kind"] == "all"]
    L += ["## Tổng thể theo cấu hình × chế độ", ""] + md_table(allr, ["label", "mode", "n", "recall@1", "recall@3", "recall@5", "mrr", "recall@budget", "latency_p50_s", "latency_p95_s"]) + [""]
    for metric in ("recall@5", "mrr", "recall@budget"):
        for kind in ("doc_type", "type"):
            sub = [r for r in summ if r["kind"] == kind]
            groups = sorted({r["group"] for r in sub})
            rows = []
            for (label, mode) in sorted({(r["label"], r["mode"]) for r in sub}):
                row = {"cfg": f"{label} / {mode}"}
                for g in groups:
                    m = next((r for r in sub if r["label"] == label and r["mode"] == mode and r["group"] == g), None)
                    row[g] = (f"{m[metric]:.3f} (n={m['n']})" if m and m[metric] is not None else "-")
                rows.append(row)
            L += [f"## {metric} theo {kind}", ""] + md_table(rows, ["cfg"] + groups, ["cấu hình / chế độ"] + groups) + [""]
    tags = [r for r in summ if r["kind"] == "tag"]
    if tags:
        L += ["## Nhóm đặc biệt (ablation VLM, phụ thuộc khóa)", ""] + md_table(tags, ["label", "mode", "group", "n", "recall@1", "recall@5", "mrr", "recall@budget"]) + [""]
    L += ["## Độ trễ trung bình từng bước (giây)", ""]
    cols = sorted({k for r in lat for k in r if k.endswith("_mean")})
    L += md_table(lat, ["label", "mode"] + cols) + [""]
    if extra.get("version"):
        L += ["## Câu phụ thuộc khóa: đúng phiên bản", "", "| cấu hình / chế độ | n | đúng phiên bản @5 | top-1 sai phiên bản |", "|---|---|---|---|"]
        for k, v in extra["version"].items():
            L.append(f"| {k} | {v['n']} | {fmt(v['version_hit@5'])} | {fmt(v['wrong_top1'])} |")
        L.append("")
    if extra.get("thresholds"):
        L += ["## Ngưỡng từ chối (chọn trên DEV)", "",
              "Quy tắc: từ chối khi điểm cao nhất < ngưỡng. `refuse_correct` = tỉ lệ câu ngoài phạm vi bị từ chối đúng; `refuse_wrong` = tỉ lệ câu có đáp án bị từ chối nhầm. "
              "Đường cong đầy đủ: thư mục `threshold_curves/`.", "",
              "| cấu hình / chế độ | tín hiệu | n có đáp án | n ngoài phạm vi | ngưỡng gợi ý (refuse_wrong ≤ 5%) | refuse_correct | refuse_wrong |", "|---|---|---|---|---|---|---|"]
        for t in extra["thresholds"]:
            p = t["pick"]
            L.append(f"| {t['cfg']} | {t['signal']} | {t['n_pos']} | {t['n_neg']} | " + (f"{p['threshold']:.4f} | {p['refuse_correct']:.3f} | {p['refuse_wrong']:.3f}" if p else "- | - | -") + " |")
        L.append("")
    if extra.get("overlap"):
        o = extra["overlap"]
        L += ["## Độ trùng từ của câu hỏi với span (nguy cơ thiên về BM25)", "",
              f"n={o['n']}; trung bình {fmt(o['mean'])}; trung vị {fmt(o['median'])}; p90 {fmt(o['p90'])}", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ một ô lưới: (câu hỏi, cấu hình, chế độ)
def signals_of(res) -> dict:
    """Điểm cao nhất của từng tín hiệu (dùng chọn ngưỡng từ chối): logit rerank, dense (cosine), bm25, rrf (hybrid)."""
    def top(name: str):
        c = (res.candidates or {}).get(name) or []
        return c[0]["score"] if c else None
    return {"max_rerank_logit": res.max_rerank_logit, "top_dense": top("dense"), "top_bm25": top("bm25"), "top_rrf": top("rrf")}


def run_cell(rt, label: str, config: str, mode: str, q: dict, ix: ChunkIndex, thr: float = 0.5, cov_mode: str = "char",
             version_docs: set[str] | None = None) -> dict:
    """Chạy retrieve cho một câu và chấm. Câu ngoài phạm vi (expected_behavior=refuse): chỉ ghi tín hiệu + độ trễ."""
    res = rt.retrieve(q["question"], config, mode, q.get("user_ctx") or None)
    ranked = res.candidates.get("ranked") or []
    ranked_ids = [r["chunk_id"] for r in ranked]
    rec = {"id": q["id"], "label": label, "config": config, "mode": mode, "doc_type": q["doc_type"], "type": q["type"], "split": q.get("split"),
           "tags": [t for t in ("ctdt_vlm", "phu_thuoc_khoa") if t in q.get("flags", [])], "timings": dict(res.timings), "signals": signals_of(res),
           "top5": ranked_ids[:5], "n_ranked": len(ranked_ids)}
    if q["expected_behavior"] != "answer":
        return {**rec, "scored": False, "oos": q["expected_behavior"] == "refuse"}
    ctx_items = (res.context or {}).get("items") or []
    m = score_question(q, ranked_ids, ctx_items, ix, thr, cov_mode)
    rec.update({"scored": True, "oos": False, "metrics": {k: m[k] for k in METRICS}, "first_hit_rank": m["first_hit_rank"],
                "ctx_ids": [it["id"] for it in ctx_items]})
    if version_docs and "phu_thuoc_khoa" in q.get("flags", []):
        rec["wrong_version_top1"] = wrong_version_top1(q, [r["doc_id"] for r in ranked], version_docs)
        rec["version_hit@5"] = m["recall@5"] > 0
    return rec


def version_stats(per_q: list[dict]) -> dict:
    acc: dict[str, list[dict]] = defaultdict(list)
    for r in per_q:
        if "version_hit@5" in r:
            acc[f"{r['label']} / {r['mode']}"].append(r)
    return {k: {"n": len(v), "version_hit@5": _mean([1.0 if r["version_hit@5"] else 0.0 for r in v]),
                "wrong_top1": _mean([1.0 if r.get("wrong_version_top1") else 0.0 for r in v if r.get("wrong_version_top1") is not None])}
            for k, v in sorted(acc.items())}


def threshold_report(per_q: list[dict], max_wrong: float = 0.05) -> tuple[list[dict], dict[str, list[dict]]]:
    """Với mỗi (nhãn, chế độ, tín hiệu): đường cong từ chối đúng/nhầm + ngưỡng gợi ý. Chỉ dùng điểm của câu in-scope-có-đáp-án vs ngoài phạm vi."""
    buckets: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: {"pos": [], "neg": []})
    for r in per_q:
        if not (r.get("scored") or r.get("oos")):
            continue
        for sig, v in (r.get("signals") or {}).items():
            if v is None:
                continue
            buckets[(r["label"], r["mode"], sig)]["neg" if r["oos"] else "pos"].append(float(v))
    table, curves = [], {}
    for (label, mode, sig), b in sorted(buckets.items()):
        if not b["pos"] or not b["neg"]:
            continue
        cv = threshold_curve(b["pos"], b["neg"])
        name = f"{label}__{mode}__{sig}"
        curves[name] = cv
        table.append({"cfg": f"{label} / {mode}", "signal": sig, "n_pos": len(b["pos"]), "n_neg": len(b["neg"]), "pick": pick_threshold(cv, max_wrong)})
    return table, curves


# ------------------------------------------------------------------ bọc cache (tiết kiệm gọi embedding/rerank lặp giữa các chế độ)
class CachedEmbedder:
    """Embed một câu một lần cho mọi chế độ/cấu hình (đã có cache SQLite, đây là cache bộ nhớ để khỏi mở DB lặp)."""

    def __init__(self, inner) -> None:
        self.inner, self.memo = inner, {}

    def embed(self, text: str):
        if text not in self.memo:
            self.memo[text] = self.inner.embed(text)
        return self.memo[text]


class CachingReranker:
    """hybrid_rerank và hybrid_rerank_fused cùng chấm trên cùng tập ứng viên => chỉ chạy mô hình một lần cho mỗi cặp (câu, văn bản)."""

    def __init__(self, inner) -> None:
        self.inner, self.memo = inner, {}

    def score_logits(self, query: str, texts: list[str]) -> list[float]:
        missing = [t for t in dict.fromkeys(texts) if (query, t) not in self.memo]
        if missing:
            for t, v in zip(missing, self.inner.score_logits(query, missing)):
                self.memo[(query, t)] = v
        return [self.memo[(query, t)] for t in texts]

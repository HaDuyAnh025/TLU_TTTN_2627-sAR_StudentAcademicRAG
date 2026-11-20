"""Thống kê chunk từ các file JSONL đã ghi: stats.json + stats.md (theo config và theo doc_type)."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

RE_PIECE = re.compile(r"::p\d+(~\d+)?$")
CONFIGS = ["c1", "c2", "c3"]


def _pct(vals: list[int], q: float) -> int:
    if not vals:
        return 0
    v = sorted(vals)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def _summ(rows: list[dict]) -> dict:
    toks = [r["n_tokens"] for r in rows]
    m = [r["metadata"] for r in rows]
    big = {x["table_id"] for x in m if x["is_table"] and x["table_mode"] == "rows"}
    small = {x["table_id"] for x in m if x["is_table"] and x["table_mode"] == "whole"}
    return {
        "docs": len({r["metadata"]["doc_id"] for r in rows}),
        "chunks": len(rows),
        "tokens_avg": round(sum(toks) / len(toks), 1) if toks else 0,
        "tokens_min": min(toks, default=0),
        "tokens_max": max(toks, default=0),
        "tokens_p95": _pct(toks, 0.95),
        "recursive_split_chunks": sum(1 for r in rows if RE_PIECE.search(r["chunk_id"])),
        "fallback_docs": sorted({x["doc_id"] for x in m if x["fallback"]}),
        "small_tables": len(small),
        "large_tables": len(big),
        "rows_to_sentences": sum((x["row_end"] - x["row_start"] + 1) for x in m if x["is_table"] and x["table_mode"] == "rows"),
        "over_max_tokens": sum(1 for t in toks if t > 512),
        "ocr_table_suspect_chunks": sum(1 for x in m if x["ocr_table_suspect"]),
    }


def _read(f: Path) -> list[dict]:
    return [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()] if f.exists() else []


def compute(out_dir: Path, skipped: list[dict], skipped_missing: list[str] | None = None) -> dict:
    """Thống kê tách 2 phần: `in_scope` (c*_chunks.jsonl, đầu vào embedding) và `excluded` (excluded_chunks.jsonl)."""
    res: dict = {"in_scope": {"configs": {}, "by_doc_type": {}}, "excluded": {"configs": {}, "by_doc_type": {}}, "skipped": skipped}
    exc_all = _read(out_dir / "chunks" / "excluded_chunks.jsonl")
    for name in CONFIGS:
        f = out_dir / "chunks" / f"{name}_chunks.jsonl"
        if not f.exists():
            continue
        for part, rows in (("in_scope", _read(f)), ("excluded", [r for r in exc_all if r["config"] == name])):
            res[part]["configs"][name] = _summ(rows)
            by: dict[str, list[dict]] = defaultdict(list)
            for r in rows:
                by[r["metadata"]["doc_type"]].append(r)
            res[part]["by_doc_type"][name] = {k: _summ(v) for k, v in sorted(by.items())}
        if name == "c3":
            ps = _read(out_dir / "chunks" / "c3_parents.jsonl")
            res["in_scope"]["configs"][name]["parents"] = len(ps)
            res["in_scope"]["configs"][name]["parent_tokens_max"] = max((p["n_tokens"] for p in ps), default=0)
    nv = out_dir / "chunks" / "c2_novlm_chunks.jsonl"
    if nv.exists():
        rows = _read(nv)
        res["ablation_c2_novlm"] = {"configs": _summ(rows), "by_doc_type": {}}
        by2: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by2[r["metadata"]["doc_type"]].append(r)
        res["ablation_c2_novlm"]["by_doc_type"] = {k: _summ(v) for k, v in sorted(by2.items())}
        c2 = [r for r in _read(out_dir / "chunks" / "c2_chunks.jsonl") if r["metadata"]["doc_id"] in {x["metadata"]["doc_id"] for x in rows}]
        res["ablation_c2_novlm"]["same_docs_with_vlm"] = _summ(c2)
    return res


def _table(title: str, data: dict) -> list[str]:
    cols = ["docs", "chunks", "tokens_avg", "tokens_min", "tokens_max", "tokens_p95", "recursive_split_chunks", "small_tables",
            "large_tables", "rows_to_sentences", "over_max_tokens", "ocr_table_suspect_chunks"]
    out = [f"### {title}", "", "| " + " | ".join(["nhóm"] + cols + ["fallback_docs"]) + " |", "|" + "---|" * (len(cols) + 2)]
    for k, v in data.items():
        out.append("| " + " | ".join([k] + [str(v[c]) for c in cols] + [str(len(v["fallback_docs"]))]) + " |")
    return out + [""]


def write_stats(out_dir: Path, names: list[str], skipped: list[dict], doc_ids: list[str]) -> dict:
    res = compute(out_dir, skipped)
    res["docs_in_meta_after_skip"] = len(doc_ids)
    (out_dir / "chunks" / "stats.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Thống kê chunking", "", f"Tài liệu được chunk: {len(doc_ids)}; bỏ qua (trung_voi / thiếu doc_meta): {len(skipped)}", ""]
    for part, label in (("in_scope", "IN_SCOPE (c*_chunks.jsonl — đầu vào embedding)"), ("excluded", "EXCLUDED (in_scope=false, excluded_chunks.jsonl)")):
        md += [f"## {label}", ""]
        md += _table("Theo cấu hình", res[part]["configs"])
        for name, data in res[part]["by_doc_type"].items():
            md += _table(f"{name.upper()} theo doc_type", data)
        for name, v in res[part]["configs"].items():
            if v["fallback_docs"]:
                md += [f"Tài liệu fallback ({name}): " + ", ".join(v["fallback_docs"]), ""]
            if "parents" in v:
                md += [f"C3: {v['parents']} parent (Điều), parent lớn nhất {v['parent_tokens_max']} token", ""]
    if "ablation_c2_novlm" in res:
        ab = res["ablation_c2_novlm"]
        md += ["## ABLATION c2_novlm (c2 với văn bản gốc, chỉ các tài liệu có trang trong table_vlm/)", ""]
        md += _table("Cùng tập tài liệu: không VLM (c2_novlm) vs có VLM (c2 chính thức)",
                     {"c2_novlm": ab["configs"], "c2 (VLM)": ab["same_docs_with_vlm"]})
    before = out_dir / "chunks" / "stats_before_vlm.json"
    if before.exists():
        b = json.loads(before.read_text(encoding="utf-8"))["in_scope"]["by_doc_type"]
        md += ["## ctdt trước/sau use_table_vlm (in_scope)", "", "| cấu hình | trạng thái | chunks | chunk bảng: bảng nhỏ | bảng lớn | dòng→câu | ocr_table_suspect |", "|---|---|---|---|---|---|---|"]
        for n_ in ("c1", "c2", "c3"):
            a, c = b.get(n_, {}).get("ctdt"), res["in_scope"]["by_doc_type"].get(n_, {}).get("ctdt")
            for lab, v in (("trước (không VLM)", a), ("sau (có VLM)", c)):
                if v:
                    md.append(f"| {n_} | {lab} | {v['chunks']} | {v['small_tables']} | {v['large_tables']} | {v['rows_to_sentences']} | {v['ocr_table_suspect_chunks']} |")
        md.append("")
    md += ["### Tài liệu bỏ qua", ""] + [f"- {s['doc_id']}: {s['ly_do']}" for s in skipped] + [""]
    (out_dir / "chunks" / "stats.md").write_text(chr(10).join(md), encoding="utf-8")
    return res

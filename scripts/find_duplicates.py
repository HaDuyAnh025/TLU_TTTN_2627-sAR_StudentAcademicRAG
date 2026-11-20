"""Tìm tài liệu nghi trùng trong data/interim/clean (CHỈ ĐỌC, KHÔNG xóa gì). Ghi data/processed/duplicates_report.csv.

Ba mức:
  exact_sha     : extract_input_sha256 (hash file gốc) trùng nhau
  exact_text    : văn bản đã nối trang + chuẩn hóa trùng hệt (hoặc trùng sau khi bỏ phần thủ tục)
  near_text     : độ giống Jaccard (shingle 5 từ) >= ngưỡng, so trong nhóm cùng tiêu đề hoặc cùng ngày ban hành

    python scripts/find_duplicates.py [--threshold 0.8]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.chunking.loader import build_document  # noqa: E402
from rag.chunking.metadata import load_doc_metas  # noqa: E402
from rag.chunking.procedural import filter_document  # noqa: E402
from rag.config import chunking_config  # noqa: E402


def shingles(text: str, n: int = 5) -> set[int]:
    w = re.findall(r"\w+", text.lower())
    return {hash(" ".join(w[i:i + n])) for i in range(max(1, len(w) - n + 1))}


def norm_title(t: str | None) -> str:
    return re.sub(r"[\W_]+", " ", (t or "").lower()).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.8)
    args = ap.parse_args()
    cfg = chunking_config()
    metas = load_doc_metas(cfg["paths"]["doc_meta"], cfg["paths"]["manifest"])
    info: dict[str, dict] = {}
    for p in sorted(cfg["paths"]["clean_dir"].glob("*.json")):
        if p.name == "_manifest.json":
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        doc = build_document(data)
        fr = filter_document(doc.text)
        info[doc.doc_id] = {
            "sha": data.get("extract_input_sha256"),
            "h_text": hashlib.sha256(doc.text.encode()).hexdigest(),
            "h_body": hashlib.sha256(re.sub(r"\s+", " ", fr.ftext).strip().lower().encode()).hexdigest(),
            "sh": shingles(fr.ftext), "n": len(doc.text),
        }
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, a: str, b: str, score: float) -> None:
        key = tuple(sorted((a, b)))
        if (kind, *key) in seen:
            return
        seen.add((kind, *key))
        ma, mb = metas[a], metas[b]
        rows.append({"kind": kind, "score": round(score, 3), "doc_a": a, "doc_b": b, "type_a": ma.doc_type, "type_b": mb.doc_type,
                     "issued_a": ma.issued_date, "issued_b": mb.issued_date, "len_a": info[a]["n"], "len_b": info[b]["n"],
                     "title_a": (ma.title or "")[:90], "title_b": (mb.title or "")[:90], "url_a": ma.source_url, "url_b": mb.source_url})

    for field, kind in (("sha", "exact_sha"), ("h_text", "exact_text"), ("h_body", "exact_text")):
        g: dict[str, list[str]] = defaultdict(list)
        for d, v in info.items():
            if v[field]:
                g[v[field]].append(d)
        for ids in g.values():
            for a, b in combinations(ids, 2):
                add(kind, a, b, 1.0)
    groups: dict[str, list[str]] = defaultdict(list)
    for d, m in metas.items():
        groups["t:" + norm_title(m.title)].append(d)
        if m.issued_date:
            groups[f"d:{m.issued_date}:{m.doc_type}"].append(d)
    for ids in groups.values():
        for a, b in combinations(sorted(set(ids)), 2):
            sa, sb = info[a]["sh"], info[b]["sh"]
            inter = len(sa & sb)
            jac = inter / max(1, len(sa | sb))
            if jac >= args.threshold:
                add("near_text", a, b, jac)
    rows.sort(key=lambda r: (r["kind"] != "exact_sha", r["kind"] != "exact_text", -r["score"]))
    out = cfg["paths"]["out_dir"] / "duplicates_report.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["kind"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} cặp nghi trùng -> {out}")
    for r in rows:
        print(f"[{r['kind']:10s} {r['score']:.2f}] {r['doc_a'][:26]} ({r['len_a']}) ~ {r['doc_b'][:26]} ({r['len_b']}) | {r['type_a']}/{r['type_b']} | "
              f"{r['issued_a']} / {r['issued_b']} | {r['title_a'][:60]}")


if __name__ == "__main__":
    main()

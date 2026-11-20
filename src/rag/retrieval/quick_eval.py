"""Đánh giá nhanh (CHƯA phải test set): 5 câu smoke test x 4 chế độ x (có/không user_ctx khóa 38) trên sar_c2.

"Đáp án đúng" được định nghĩa TRƯỚC khi chạy (xem CASES): vị từ trên payload của chunk. Báo hạng của chunk đúng đầu tiên trong thứ hạng
cuối của từng chế độ (sau khử trùng lặp; hybrid_rerank chỉ xếp hạng n_rerank ứng viên đầu sau RRF, ngoài đó = "-").
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from rag.config import EVAL_DIR
from rag.retrieval.context import breadcrumb
from rag.retrieval.retriever import MODES, Retriever

QC = {"drive-13k1p5GWL6r021YkWJYY87nhTmKjrK6rB": "2024", "drive-1gYObSE-JoCLLr0huk80J_SrylGCx1YeF": "2025",
      "drive-1Q0FM6LZT2K29545yQl2yoXT4V-PgA2UA": "2026"}
HOC_PHI_38 = {"drive-1CO2TKAyijKkiF3442zbZdyfsioJUQzuv", "drive-1QeigJtogbG2X25Yi1qcHg-hfMsWEGQEP"}
QD_CHUYEN_NGANH = "drive-1fAwLCocJRGWb-N9zhlwVxc5yvy_SEdvm"
LICH_THI = "drive-1ud6p7cPzK4GUQ3GgKtKAKKa6QsoV5l3F"


def _bc(pl: dict) -> str:
    return breadcrumb(pl["embed_text"])


CASES = [
    ("Sinh viên được đăng ký tối đa bao nhiêu tín chỉ một học kỳ?",
     "Điều 'Tổ chức đăng ký học' (Đ.10 bản 2024/2026, Đ.9 bản 2025) của Quy chế đào tạo",
     lambda pl, ctx: pl["doc_id"] in QC and re.search(r"Điều (9|10)\. Tổ chức đăng ký học", _bc(pl)) is not None),
    ("Học phí học lại khóa 38 là bao nhiêu?", "QĐ học phí học lại khóa 38 (2 văn bản: ...JUQzuv, ...EGQEP)",
     lambda pl, ctx: pl["doc_id"] in HOC_PHI_38),
    ("Học phần AE321 bao nhiêu tín chỉ?", "chunk bảng chứa dòng AE321",
     lambda pl, ctx: bool(pl.get("is_table")) and "AE321" in pl["content"]),
    ("Điều kiện để chuyển ngành là gì?",
     "Quy định chuyển ngành hiện hành (mục 'Điều kiện') hoặc Điều chuyển ngành của Quy chế (Đ.21 bản 2024, Đ.25 bản 2025)",
     lambda pl, ctx: (pl["doc_id"] == QD_CHUYEN_NGANH and "Điều kiện" in _bc(pl))
     or (pl["doc_id"] in QC and (re.search(r"Điều \d+\. [^>]*chuyển ngành", _bc(pl), re.I) is not None
                                 or (QC[pl["doc_id"]] == "2025" and "::d25::" in pl["chunk_id"])))),
    ("Lịch thi học kỳ I năm học 2025 - 2026", "THÔNG BÁO Lịch thi học kỳ I, năm học 2025 - 2026 (doc ...5l3F)",
     lambda pl, ctx: pl["doc_id"] == LICH_THI),
]
CTXS = [None, {"khoa": 38}]


def first_rank(rows_by_id: dict, ranked: list[dict], pred) -> int | None:
    for r in ranked:
        if pred(rows_by_id[r["chunk_id"]], None):
            return r["rank"]
    return None


def run(config: str = "c2", out_dir: Path | None = None) -> str:
    rt = Retriever()
    table, timings, dups, scores = [], {}, [], []
    for q, _, pred in CASES:
        for ctx in CTXS:
            row = {"q": q, "ctx": "khóa 38" if ctx else "—", "ranks": {}}
            for mode in MODES:
                res = rt.retrieve(q, config, mode, ctx)
                lookup = {c["chunk_id"]: c["payload"] for c in res.final}
                # cần payload của mọi ứng viên đã xếp hạng: lấy từ Qdrant theo chunk_id đã xếp hạng
                ids = [r["chunk_id"] for r in res.candidates["ranked"]]
                missing = [i for i in ids if i not in lookup]
                if missing:
                    from qdrant_client import models
                    from rag.embedding.qdrant_store import point_id
                    for rec in rt.client.retrieve(rt.cfg["qdrant"]["collections"][config], ids=[point_id(i) for i in missing], with_payload=True):
                        lookup[rec.payload["chunk_id"]] = rec.payload
                row["ranks"][mode] = first_rank(lookup, res.candidates["ranked"], pred)
                for k, v in res.timings.items():
                    timings.setdefault(k, []).append(v)
                for d in res.duplicates:
                    dups.append({"q": q, "mode": mode, **d})
                if res.max_rerank_score is not None:
                    scores.append((q, row["ctx"], round(res.max_rerank_score, 4)))
                row.setdefault("top1", {})[mode] = f"{res.final[0]['chunk_id'][-30:]} | {_bc(res.final[0]['payload'])[:60]}" if res.final else "-"
            table.append(row)
    fmt = lambda x: "-" if x is None else str(x)
    md = ["# Đánh giá nhanh retrieval (sar_%s)" % config, "", "Hạng của chunk đúng đầu tiên (- = không nằm trong ứng viên).", "",
          "| # | Câu hỏi | user_ctx | dense | bm25 | hybrid | hybrid_rerank |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(table):
        md.append(f"| {i // 2 + 1} | {r['q']} | {r['ctx']} | " + " | ".join(fmt(r["ranks"][m]) for m in MODES) + " |")
    md += ["", "## Đáp án đúng (định nghĩa trước khi chạy)", ""] + [f"{i}. {q} → {d}" for i, (q, d, _) in enumerate(CASES, 1)]
    md += ["", "## Thời gian trung bình mỗi bước (giây, mọi lần chạy)", "", "| bước | trung bình | lớn nhất | số lần |", "|---|---|---|---|"]
    for k, v in timings.items():
        md.append(f"| {k} | {statistics.mean(v):.3f} | {max(v):.3f} | {len(v)} |")
    md += ["", "## max_rerank_score", ""] + [f"- {q} [{c}]: {s}" for q, c, s in scores]
    md += ["", f"## Khử trùng lặp ({len(dups)} trường hợp, mọi chế độ)", ""]
    seen = set()
    for d in dups:
        key = (d["kept"], tuple(d["dropped"]))
        if key not in seen:
            seen.add(key)
            md.append(f"- giữ `{d['kept'][-40:]}`, bỏ {[x[-30:] for x in d['dropped']]} (câu: {d['q'][:40]}, chế độ {d['mode']})")
    text = "\n".join(md)
    out_dir = out_dir or EVAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "retrieval_quick_eval.md").write_text(text, encoding="utf-8")
    (out_dir / "retrieval_quick_eval.json").write_text(json.dumps({"table": table, "timings": timings, "duplicates": dups}, ensure_ascii=False, indent=1), encoding="utf-8")
    return text

"""Ghép context theo NGÂN SÁCH TOKEN CỐ ĐỊNH (cl100k_base) cho mọi cấu hình; C3: đổi child -> parent (SQLite), gộp parent trùng."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _enc():
    from rag.config import chunking_config
    chunking_config()  # đặt TIKTOKEN_CACHE_DIR
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")


def breadcrumb(embed_text: str) -> str:
    if embed_text.startswith("["):
        i = embed_text.find("] ")
        if i > 0:
            return embed_text[1:i]
    return embed_text[:80]


def _children_to_items(final: list[dict], config: str, parents_db: Path | None) -> list[dict]:
    """Mục context theo thứ tự điểm child cao nhất; C3 gộp các child cùng parent thành một mục."""
    items: list[dict] = []
    seen: dict[str, dict] = {}
    db = sqlite3.connect(str(parents_db)) if (config == "c3" and parents_db and Path(parents_db).exists()) else None
    try:
        for c in final:
            pl = c["payload"]
            pid = pl.get("parent_id") if db is not None else None
            row = db.execute("SELECT embed_text, content, metadata_json FROM parents WHERE parent_id=?", (pid,)).fetchone() if pid else None
            if row is None:  # không phải C3 hoặc không có parent: dùng chính chunk
                items.append({"id": c["chunk_id"], "text": pl["embed_text"], "meta": pl, "children": [c["chunk_id"]], "parent": False})
                continue
            if pid in seen:
                seen[pid]["children"].append(c["chunk_id"])
                continue
            it = {"id": pid, "text": row[0], "meta": json.loads(row[2]), "children": [c["chunk_id"]], "parent": True}
            seen[pid] = it
            items.append(it)
    finally:
        if db is not None:
            db.close()
    return items


def build_context(final: list[dict], config: str, budget: int, min_truncate: int = 100, parents_db: Path | None = None) -> dict:
    """Mục theo thứ tự xếp hạng; mục không vừa ngân sách bị cắt nếu còn >= min_truncate token, nếu không thì dừng."""
    enc = _enc()
    out, used = [], 0
    for it in _children_to_items(final, config, parents_db):
        toks = enc.encode(it["text"], disallowed_special=())
        n, truncated = len(toks), False
        if used + n > budget:
            room = budget - used
            if room < min_truncate and out:
                break
            toks, n, truncated = toks[:max(room, 0)], max(room, 0), True
        meta = it["meta"]
        out.append({"id": it["id"], "parent": it["parent"], "children": it["children"],
                    "text": enc.decode(toks) if truncated else it["text"], "tokens": n, "truncated": truncated,
                    "citation": {"breadcrumb": breadcrumb(it["text"]), "doc_id": meta.get("doc_id"), "page_start": meta.get("page_start"),
                                 "page_end": meta.get("page_end"), "source_url": meta.get("source_url")}})
        used += n
        if truncated:
            break
    text = "\n\n".join(f"[{i}] {x['text']}" for i, x in enumerate(out, 1))
    return {"items": out, "tokens": used, "budget": budget, "text": text, "sources": [x["citation"] for x in out]}

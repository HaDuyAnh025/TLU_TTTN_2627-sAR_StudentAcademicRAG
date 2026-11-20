"""Qdrant: tạo collection (dense_small, dense_large, sparse bm25 modifier=IDF), payload index, upsert, đồng bộ xóa điểm thừa,
bộ lọc theo status / in_scope / khóa (null = áp dụng cho tất cả), và kho cha C3 trong SQLite."""
from __future__ import annotations

import json
import random
import sqlite3
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "sar.thanglong.chunks")
DENSE = {"small": ("dense_small", 1536), "large": ("dense_large", 3072)}
SPARSE = "bm25"
PAYLOAD_INDEXES = {
    "doc_id": models.PayloadSchemaType.KEYWORD, "doc_type": models.PayloadSchemaType.KEYWORD,
    "status": models.PayloadSchemaType.KEYWORD, "in_scope": models.PayloadSchemaType.BOOL,
    "bac_dao_tao": models.PayloadSchemaType.KEYWORD, "khoa_tu": models.PayloadSchemaType.INTEGER,
    "khoa_den": models.PayloadSchemaType.INTEGER, "nganh": models.PayloadSchemaType.KEYWORD,
    "is_table": models.PayloadSchemaType.BOOL, "is_preamble": models.PayloadSchemaType.BOOL,
    "config": models.PayloadSchemaType.KEYWORD,
}
PAYLOAD_REQUIRED = ("chunk_id", "embed_text", "content", "n_tokens", "config", "doc_id", "doc_type", "status", "in_scope",
                    "bac_dao_tao", "khoa_tu", "khoa_den", "nganh", "is_table", "is_preamble")


def point_id(chunk_id: str) -> str:
    """uuid5 ổn định theo chunk_id: upsert lặp lại không tạo bản trùng."""
    return str(uuid.uuid5(NAMESPACE, chunk_id))


def make_payload(chunk: dict) -> dict:
    """Toàn bộ metadata (trải phẳng để lọc được) + chunk_id, config, embed_text, content, n_tokens."""
    return {**chunk["metadata"], "chunk_id": chunk["chunk_id"], "config": chunk["config"], "embed_text": chunk["embed_text"],
            "content": chunk["content"], "n_tokens": chunk["n_tokens"]}


def connect(url: str) -> QdrantClient:
    return QdrantClient(url=url, timeout=120)


def ensure_collection(client: QdrantClient, name: str) -> bool:
    """Tạo collection nếu chưa có (cùng payload index). Trả True nếu vừa tạo."""
    if client.collection_exists(name):
        return False
    client.create_collection(
        collection_name=name,
        vectors_config={v: models.VectorParams(size=d, distance=models.Distance.COSINE) for v, d in DENSE.values()},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)})
    for field, schema in PAYLOAD_INDEXES.items():
        client.create_payload_index(name, field_name=field, field_schema=schema)
    return True


def upsert_points(client: QdrantClient, name: str, points: list[models.PointStruct], batch: int = 256) -> None:
    for i in range(0, len(points), batch):
        client.upsert(name, points=points[i:i + batch], wait=True)


def sync_delete_stale_ids(client: QdrantClient, name: str, keep_ids: set[str]) -> list[str]:
    """Xóa điểm có id không còn trong file chunk. Trả danh sách chunk_id của các điểm đã xóa."""
    stale: list[str] = []
    stale_cids: list[str] = []
    offset = None
    while True:
        recs, offset = client.scroll(name, limit=1000, offset=offset, with_payload=["chunk_id"], with_vectors=False)
        for r in recs:
            if str(r.id) not in keep_ids:
                stale.append(str(r.id))
                stale_cids.append((r.payload or {}).get("chunk_id", str(r.id)))
        if offset is None:
            break
    if stale:
        client.delete(name, points_selector=models.PointIdsList(points=stale), wait=True)
    return stale_cids


def sync_delete_stale(client: QdrantClient, name: str, keep_ids: set[str]) -> int:
    return len(sync_delete_stale_ids(client, name, keep_ids))


def build_filter(status: str | None = "hieu_luc", in_scope: bool | None = True, khoa: int | None = None,
                 bac_dao_tao: str | None = None, nganh: str | None = None) -> models.Filter | None:
    """Bộ lọc mặc định cho truy vấn. Khóa K: (khoa_tu null HOẶC <= K) VÀ (khoa_den null HOẶC >= K); nganh null = tất cả ngành."""
    must: list = []
    if status:
        must.append(models.FieldCondition(key="status", match=models.MatchValue(value=status)))
    if in_scope is not None:
        must.append(models.FieldCondition(key="in_scope", match=models.MatchValue(value=in_scope)))
    if bac_dao_tao:
        must.append(models.FieldCondition(key="bac_dao_tao", match=models.MatchValue(value=bac_dao_tao)))
    if khoa is not None:
        must.append(models.Filter(should=[models.IsNullCondition(is_null=models.PayloadField(key="khoa_tu")),
                                          models.FieldCondition(key="khoa_tu", range=models.Range(lte=khoa))]))
        must.append(models.Filter(should=[models.IsNullCondition(is_null=models.PayloadField(key="khoa_den")),
                                          models.FieldCondition(key="khoa_den", range=models.Range(gte=khoa))]))
    if nganh:
        must.append(models.Filter(should=[models.IsNullCondition(is_null=models.PayloadField(key="nganh")),
                                          models.FieldCondition(key="nganh", match=models.MatchValue(value=nganh))]))
    return models.Filter(must=must) if must else None


def verify_collection(client: QdrantClient, name: str, expected_n: int, model: str, n_sample: int = 5, seed: int = 42) -> dict:
    """Số điểm == số dòng file chunk; 0 điểm in_scope=false; mẫu ngẫu nhiên: đủ trường payload, vector đúng chiều, sparse không rỗng."""
    n = client.count(name, exact=True).count
    n_out = client.count(name, exact=True, count_filter=models.Filter(must=[
        models.FieldCondition(key="in_scope", match=models.MatchValue(value=False))])).count
    ids, offset = [], None
    while True:
        recs, offset = client.scroll(name, limit=1000, offset=offset, with_payload=False, with_vectors=False)
        ids += [r.id for r in recs]
        if offset is None:
            break
    sample = random.Random(seed).sample(ids, min(n_sample, len(ids)))
    vname, dim = DENSE[model]
    problems, rows = [], []
    for r in client.retrieve(name, ids=sample, with_payload=True, with_vectors=True):
        miss = [k for k in PAYLOAD_REQUIRED if k not in r.payload]
        vec, sp = (r.vector or {}).get(vname), (r.vector or {}).get(SPARSE)
        ok_dim = vec is not None and len(vec) == dim
        ok_sp = sp is not None and len(sp.indices) > 0
        if miss or not ok_dim or not ok_sp:
            problems.append({"chunk_id": r.payload.get("chunk_id"), "thieu_payload": miss, "dim_ok": ok_dim, "sparse_ok": ok_sp})
        rows.append({"chunk_id": r.payload.get("chunk_id"), "n_payload_fields": len(r.payload), "dim": None if vec is None else len(vec),
                     "sparse_nnz": 0 if sp is None else len(sp.indices)})
    return {"collection": name, "points": n, "expected": expected_n, "count_ok": n == expected_n, "in_scope_false": n_out,
            "sample": rows, "problems": problems, "ok": n == expected_n and n_out == 0 and not problems}


# ------------------------------------------------------------------------------------------------ kho cha C3
def load_parents(db_path: Path, rows: list[dict]) -> dict:
    """Nạp c3_parents vào SQLite (INSERT OR REPLACE) và xóa parent không còn trong file. Trả {n, deleted}."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path))
    try:
        db.execute("CREATE TABLE IF NOT EXISTS parents(parent_id TEXT PRIMARY KEY, embed_text TEXT, content TEXT, metadata_json TEXT)")
        db.executemany("INSERT OR REPLACE INTO parents(parent_id, embed_text, content, metadata_json) VALUES (?,?,?,?)",
                       [(r["parent_id"], r["embed_text"], r["content"], json.dumps(r["metadata"], ensure_ascii=False)) for r in rows])
        keep = {r["parent_id"] for r in rows}
        old = {r[0] for r in db.execute("SELECT parent_id FROM parents")}
        stale = sorted(old - keep)
        db.executemany("DELETE FROM parents WHERE parent_id=?", [(s,) for s in stale])
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM parents").fetchone()[0]
    finally:
        db.close()
    return {"n": n, "deleted": len(stale)}

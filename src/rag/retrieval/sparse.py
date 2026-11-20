"""Truy xuất BM25: query_to_sparse (đã có chuẩn hóa miền) rồi query_points trên vector `bm25` (IDF do Qdrant áp)."""
from __future__ import annotations

from rag.embedding.bm25 import query_to_sparse
from rag.embedding.qdrant_store import SPARSE


def search_sparse(client, collection: str, text: str, flt, k: int):
    return client.query_points(collection, query=query_to_sparse(text), using=SPARSE, query_filter=flt, limit=k, with_payload=True).points

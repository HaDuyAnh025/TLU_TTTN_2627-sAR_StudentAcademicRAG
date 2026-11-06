"""Các dependency dùng chung. Test có thể thay bằng app.dependency_overrides[...]."""

from functools import lru_cache

from qdrant_client import QdrantClient

from app.core.cache import Cache
from app.core.config import get_settings
from app.retrieval.base import Retriever
from app.retrieval.embedder import Embedder, build_embedder
from app.retrieval.qdrant_retriever import QdrantRetriever, build_qdrant_client


@lru_cache
def get_qdrant_client() -> QdrantClient:
    return build_qdrant_client(get_settings())


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder(get_settings())


@lru_cache
def get_retriever() -> Retriever:
    """Đổi retriever ở đây khi nhóm AI có bản mới (MMR / hybrid / rerank)."""
    s = get_settings()
    return QdrantRetriever(get_qdrant_client(), s.qdrant_collection, get_embedder())


@lru_cache
def get_cache() -> Cache:
    return Cache(get_settings().redis_url)

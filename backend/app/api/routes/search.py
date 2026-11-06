import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_cache, get_embedder, get_retriever
from app.core.cache import Cache
from app.core.config import get_settings
from app.retrieval.base import Retriever, RetrieverUnavailable
from app.retrieval.embedder import Embedder
from app.schemas.api import ErrorResponse, SearchResponse, SearchResult

router = APIRouter(tags=["search"])


def _cache_key(q: str, top_k: int, categories: list[str] | None, model: str) -> str:
    s = get_settings()
    raw = json.dumps([s.qdrant_collection, model, q, top_k, sorted(categories or [])], ensure_ascii=False)
    return "search:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Tìm đoạn tài liệu liên quan trong vector DB (không qua LLM)",
    responses={503: {"model": ErrorResponse, "description": "Qdrant chưa sẵn sàng / chưa có dữ liệu"}},
)
def search(
    q: str = Query(..., min_length=1, max_length=500, description="Câu hỏi / từ khóa"),
    top_k: int | None = Query(None, ge=1, description="Số kết quả (mặc định 5, tối đa 20)"),
    category: list[str] | None = Query(None, description="Lọc theo nhóm tài liệu, truyền nhiều lần được"),
    retriever: Retriever = Depends(get_retriever),
    embedder: Embedder = Depends(get_embedder),
    cache: Cache = Depends(get_cache),
) -> SearchResponse:
    s = get_settings()
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="q không được để trống")
    k = min(top_k or s.search_default_top_k, s.search_max_top_k)

    started = time.perf_counter()
    key = _cache_key(q, k, category, embedder.name)
    hit = cache.get_json(key)
    if hit is not None:
        results = [SearchResult(**r) for r in hit]
        cached = True
    else:
        try:
            chunks = retriever.search(q, top_k=k, categories=category)
        except RetrieverUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from None
        results = [SearchResult(**c.__dict__) for c in chunks]
        cache.set_json(key, [r.model_dump() for r in results], s.search_cache_ttl)
        cached = False

    return SearchResponse(
        query=q,
        top_k=k,
        results=results,
        took_ms=int((time.perf_counter() - started) * 1000),
        cached=cached,
    )

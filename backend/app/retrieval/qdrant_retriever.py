"""Retriever tìm kiếm tương đồng (cosine) trên Qdrant.

Payload mỗi điểm trong collection theo "hợp đồng dữ liệu" ở docs/api_contract.md mục 4:
chunk_id, doc_id, text, title, source_url, category, (tùy chọn) section, page, issued_date...
"""

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.config import Settings
from app.retrieval.base import RetrievedChunk, RetrieverUnavailable
from app.retrieval.embedder import Embedder

# Các khóa payload được đưa thẳng thành trường riêng; còn lại cho vào metadata
_CORE_KEYS = {"chunk_id", "doc_id", "text", "title", "source_url", "category"}


def build_qdrant_client(settings: Settings) -> QdrantClient:
    if settings.qdrant_url == ":memory:":
        return QdrantClient(location=":memory:")
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=10)


class QdrantRetriever:
    def __init__(self, client: QdrantClient, collection: str, embedder: Embedder):
        self.client = client
        self.collection = collection
        self.embedder = embedder

    def search(
        self, query: str, top_k: int = 5, categories: list[str] | None = None
    ) -> list[RetrievedChunk]:
        try:
            if not self.client.collection_exists(self.collection):
                raise RetrieverUnavailable(
                    f"Chưa có collection '{self.collection}' trong Qdrant. "
                    "Chạy index (T3-03) hoặc scripts/seed_qdrant.py để có dữ liệu thử."
                )
            query_filter = None
            if categories:
                query_filter = qm.Filter(
                    must=[qm.FieldCondition(key="category", match=qm.MatchAny(any=categories))]
                )
            res = self.client.query_points(
                collection_name=self.collection,
                query=self.embedder.embed_query(query),
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
            )
        except RetrieverUnavailable:
            raise
        except (ResponseHandlingException, ConnectionError, OSError) as e:
            raise RetrieverUnavailable(f"Không kết nối được Qdrant: {e}") from e
        except UnexpectedResponse as e:
            # Hay gặp nhất: số chiều vector của mô hình embedding khác với lúc index
            raise RetrieverUnavailable(f"Qdrant báo lỗi khi truy vấn: {e}") from e

        chunks = []
        for p in res.points:
            pl = p.payload or {}
            chunks.append(
                RetrievedChunk(
                    chunk_id=str(pl.get("chunk_id") or p.id),
                    doc_id=pl.get("doc_id"),
                    text=pl.get("text", ""),
                    score=float(p.score),
                    title=pl.get("title"),
                    source_url=pl.get("source_url"),
                    category=pl.get("category"),
                    metadata={k: v for k, v in pl.items() if k not in _CORE_KEYS},
                )
            )
        return chunks

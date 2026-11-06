"""Mô hình embedding dùng để mã hóa câu hỏi khi tìm kiếm.

QUAN TRỌNG: câu hỏi phải được mã hóa bằng ĐÚNG mô hình (và tiền tố) đã dùng khi index
tài liệu vào Qdrant (T3-03), nếu không kết quả tìm kiếm sẽ vô nghĩa.
"""

import hashlib
import math
import re
from functools import cached_property
from typing import Protocol

from app.core.config import Settings


class Embedder(Protocol):
    name: str

    @property
    def dim(self) -> int: ...

    def embed_query(self, text: str) -> list[float]: ...

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Dùng được cho BGE-M3, multilingual-e5, Vietnamese SBERT (các ứng viên ở T3-05)."""

    def __init__(self, model_name: str, query_prefix: str = "", passage_prefix: str = ""):
        self.name = model_name
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix

    @cached_property
    def _model(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Chưa cài sentence-transformers: pip install -r requirements-ml.txt "
                "(hoặc đặt EMBEDDING_PROVIDER=hash để chạy thử không cần mô hình)"
            ) from e
        return SentenceTransformer(self.name)

    @property
    def dim(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode(self.query_prefix + text, normalize_embeddings=True).tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            [self.passage_prefix + t for t in texts], normalize_embeddings=True, batch_size=32
        )
        return vecs.tolist()


class HashEmbedder:
    """Embedding giả lập theo từ khóa (bag-of-words băm). KHÔNG dùng cho sản phẩm.

    Chỉ để chạy test / thử API khi chưa tải mô hình thật: câu hỏi có nhiều từ trùng với
    đoạn văn thì điểm cao hơn.
    """

    _token = re.compile(r"\w+", re.UNICODE)

    def __init__(self, dim: int = 384):
        self.name = f"hash-{dim}"
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for tok in self._token.findall(text.lower()):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder(settings.embedding_dim)
    return SentenceTransformerEmbedder(
        settings.embedding_model,
        query_prefix=settings.embedding_query_prefix,
        passage_prefix=settings.embedding_passage_prefix,
    )

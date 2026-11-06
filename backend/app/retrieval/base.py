"""Giao diện chung của bộ tìm kiếm (retriever).

API chỉ phụ thuộc vào `Retriever` này. Khi nhóm AI (T4-01 MMR, T4-02 hybrid, T4-03 rerank)
làm retriever mới, chỉ cần viết lớp có hàm `search(...)` cùng chữ ký rồi đăng ký trong
`app/api/deps.py::get_retriever`, không phải sửa route.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class RetrieverUnavailable(RuntimeError):
    """Vector DB chưa sẵn sàng (chưa chạy, chưa có collection...). API trả 503."""


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float
    doc_id: str | None = None
    title: str | None = None
    source_url: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever(Protocol):
    def search(
        self, query: str, top_k: int = 5, categories: list[str] | None = None
    ) -> list[RetrievedChunk]: ...

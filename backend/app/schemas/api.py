"""Schema request/response của API (T3-07). Đây là "hợp đồng" giữa backend và Web UI:
mọi thay đổi ở đây sẽ thay đổi docs/openapi.json, cần báo cho cả nhóm."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Không tìm thấy cuộc hội thoại"])


# ---------- Nguồn trích dẫn ----------


class CitationOut(BaseModel):
    rank: int = Field(description="Thứ tự nguồn, dùng để hiển thị [1], [2]... trong câu trả lời")
    chunk_id: str
    doc_id: str | None = None
    title: str | None = None
    source_url: str | None = None
    snippet: str = Field(description="Đoạn trích của tài liệu nguồn")
    score: float | None = None
    metadata: dict[str, Any] | None = None


# ---------- POST /chat ----------


class ChatFilters(BaseModel):
    categories: list[str] | None = Field(
        default=None,
        description="Chỉ tìm trong các nhóm tài liệu này (vd. quy_che, hoc_phi, lich_thi)",
        examples=[["quy_che", "hoc_phi"]],
    )


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Bỏ trống để bắt đầu cuộc hội thoại mới"
    )
    message: str = Field(min_length=1, max_length=2000, examples=["Điều kiện xét tốt nghiệp là gì?"])
    user_id: str | None = Field(default=None, max_length=64, description="Mã người dùng/phiên (tùy chọn)")
    top_k: int = Field(default=5, ge=1, le=20, description="Số nguồn tối đa dùng để trả lời")
    filters: ChatFilters | None = None
    stream: bool = Field(
        default=False,
        description="true: trả về Server-Sent Events (text/event-stream) thay vì JSON",
    )

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message không được để trống")
        return v


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID = Field(description="id tin nhắn trả lời, dùng khi gửi POST /feedback")
    answer: str
    citations: list[CitationOut]
    created_at: datetime
    mode: Literal["mock", "rag"] = Field(description="mock: câu trả lời giả lập (tuần 3)")


# ---------- GET /conversations/{id} ----------


class FeedbackSummary(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    citations: list[CitationOut] = []
    feedback: FeedbackSummary | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    user_id: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


# ---------- POST /feedback ----------


class FeedbackCreate(BaseModel):
    message_id: uuid.UUID = Field(description="id tin nhắn assistant cần đánh giá")
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    rating: Literal["up", "down"]
    comment: str | None
    created_at: datetime
    updated_at: datetime


# ---------- GET /suggestions ----------


class Suggestion(BaseModel):
    id: str
    text: str
    category: str


class SuggestionsResponse(BaseModel):
    items: list[Suggestion]


# ---------- GET /search ----------


class SearchResult(BaseModel):
    chunk_id: str
    doc_id: str | None = None
    text: str
    score: float
    title: str | None = None
    source_url: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = {}


class SearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[SearchResult]
    took_ms: int
    cached: bool = Field(description="true nếu kết quả lấy từ cache Redis")


# ---------- /health ----------


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, str] = {}

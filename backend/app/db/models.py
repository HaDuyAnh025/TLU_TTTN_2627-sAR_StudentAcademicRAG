"""Bảng dữ liệu của hệ thống hỏi đáp (T3-07): conversations, messages, citations, feedback.

Sơ đồ quan hệ: docs/db_schema.md. Mỗi khi sửa file này phải tạo migration Alembic mới
(`alembic revision --autogenerate -m "..."`) và kiểm tra bằng `alembic check`.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# JSONB trên PostgreSQL, JSON thường trên SQLite (dùng khi test)
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    # Gán thời gian phía Python (có micro giây) để tin nhắn trong cùng một transaction
    # vẫn có thứ tự; now() của PostgreSQL trả cùng một giá trị trong một transaction.
    return datetime.now(timezone.utc)


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    extra: Mapped[dict | None] = mapped_column("metadata", JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e])
    )
    content: Mapped[str] = mapped_column(Text)
    # Thông tin sinh câu trả lời (chỉ có ở tin nhắn assistant)
    model: Mapped[str | None] = mapped_column(String(100))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    extra: Mapped[dict | None] = mapped_column("metadata", JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list["Citation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Citation.rank",
    )
    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class Citation(Base):
    """Đoạn tài liệu (chunk) được dùng làm nguồn cho một câu trả lời."""

    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("message_id", "rank", name="uq_citations_message_id_rank"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger)  # 1 = nguồn liên quan nhất, dùng cho [1], [2]...
    chunk_id: Mapped[str] = mapped_column(String(128))  # khớp payload.chunk_id trong Qdrant
    doc_id: Mapped[str | None] = mapped_column(String(128))  # vd. tb-2281, nganh-cong-nghe-thong-tin
    title: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict | None] = mapped_column("metadata", JSONType)  # category, section, page...

    message: Mapped[Message] = relationship(back_populates="citations")


class Feedback(Base):
    """Đánh giá của người dùng cho một câu trả lời: 1 = hữu ích, -1 = không hữu ích."""

    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="rating_values"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    message: Mapped[Message] = relationship(back_populates="feedback")

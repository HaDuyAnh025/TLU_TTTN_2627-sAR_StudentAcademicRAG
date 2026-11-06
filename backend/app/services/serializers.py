"""Chuyển đối tượng DB sang schema API."""

from app.db.models import Citation, Conversation, Feedback, Message
from app.schemas.api import (
    CitationOut,
    ConversationOut,
    FeedbackOut,
    FeedbackSummary,
    MessageOut,
)


def rating_to_str(rating: int) -> str:
    return "up" if rating > 0 else "down"


def citation_out(c: Citation) -> CitationOut:
    return CitationOut(
        rank=c.rank,
        chunk_id=c.chunk_id,
        doc_id=c.doc_id,
        title=c.title,
        source_url=c.source_url,
        snippet=c.snippet,
        score=c.score,
        metadata=c.extra,
    )


def message_out(m: Message) -> MessageOut:
    fb = None
    if m.feedback is not None:
        fb = FeedbackSummary(rating=rating_to_str(m.feedback.rating), comment=m.feedback.comment)
    return MessageOut(
        id=m.id,
        role=m.role.value,
        content=m.content,
        created_at=m.created_at,
        citations=[citation_out(c) for c in m.citations],
        feedback=fb,
    )


def conversation_out(conv: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        user_id=conv.user_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[message_out(m) for m in conv.messages],
    )


def feedback_out(fb: Feedback) -> FeedbackOut:
    return FeedbackOut(
        id=fb.id,
        message_id=fb.message_id,
        rating=rating_to_str(fb.rating),
        comment=fb.comment,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )

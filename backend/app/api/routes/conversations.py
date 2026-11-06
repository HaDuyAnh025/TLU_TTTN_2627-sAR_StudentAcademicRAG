import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Conversation, Message
from app.db.session import get_db
from app.schemas.api import ConversationOut, ErrorResponse
from app.services.serializers import conversation_out

router = APIRouter(tags=["conversations"])


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationOut,
    summary="Lấy toàn bộ tin nhắn của một cuộc hội thoại (kèm nguồn và feedback)",
    responses={404: {"model": ErrorResponse}},
)
def get_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db)) -> ConversationOut:
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(
            selectinload(Conversation.messages).selectinload(Message.citations),
            selectinload(Conversation.messages).selectinload(Message.feedback),
        )
    )
    conv = db.scalars(stmt).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc hội thoại")
    return conversation_out(conv)

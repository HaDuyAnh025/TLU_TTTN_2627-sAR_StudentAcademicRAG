import json
import re
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Conversation, Message
from app.db.session import get_db
from app.schemas.api import ChatRequest, ChatResponse, ErrorResponse
from app.services.chat_service import ConversationNotFound, handle_chat
from app.services.serializers import citation_out

router = APIRouter(tags=["chat"])

_SSE_DOC = """Khi `stream=true`, phản hồi là `text/event-stream` gồm các sự kiện theo thứ tự:

| event | data (JSON) |
|---|---|
| `start` | `{"conversation_id", "message_id"}` |
| `token` | `{"delta": "<một đoạn chữ>"}` (lặp nhiều lần) |
| `citations` | `{"citations": [Citation...]}` |
| `done` | toàn bộ `ChatResponse` |
| `error` | `{"detail": "..."}` (chỉ khi lỗi giữa chừng) |
"""


def _to_response(conv: Conversation, msg: Message) -> ChatResponse:
    return ChatResponse(
        conversation_id=conv.id,
        message_id=msg.id,
        answer=msg.content,
        citations=[citation_out(c) for c in msg.citations],
        created_at=msg.created_at,
        mode="mock",
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_mock(resp: ChatResponse) -> Iterator[str]:
    delay = get_settings().mock_stream_delay_ms / 1000
    yield _sse("start", {"conversation_id": str(resp.conversation_id), "message_id": str(resp.message_id)})
    for piece in re.findall(r"\S+\s*", resp.answer):
        yield _sse("token", {"delta": piece})
        if delay:
            time.sleep(delay)
    yield _sse("citations", {"citations": [c.model_dump(mode="json") for c in resp.citations]})
    yield _sse("done", resp.model_dump(mode="json"))


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Gửi câu hỏi, nhận câu trả lời kèm nguồn (tuần 3: MOCK)",
    description="Bỏ trống `conversation_id` để tạo hội thoại mới.\n\n" + _SSE_DOC,
    responses={
        200: {"content": {"text/event-stream": {}}},
        404: {"model": ErrorResponse, "description": "conversation_id không tồn tại"},
    },
)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        conv, msg = handle_chat(db, req)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc hội thoại") from None
    resp = _to_response(conv, msg)
    if req.stream:
        return StreamingResponse(
            _stream_mock(resp),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return resp

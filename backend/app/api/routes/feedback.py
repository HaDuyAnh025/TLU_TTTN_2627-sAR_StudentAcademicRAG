from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db.models import Feedback, Message, MessageRole
from app.db.session import get_db
from app.schemas.api import ErrorResponse, FeedbackCreate, FeedbackOut
from app.services.serializers import feedback_out

router = APIRouter(tags=["feedback"])


@router.post(
    "/feedback",
    response_model=FeedbackOut,
    status_code=201,
    summary="Đánh giá một câu trả lời (up/down). Gửi lại sẽ cập nhật đánh giá cũ",
    responses={
        200: {"model": FeedbackOut, "description": "Đã cập nhật đánh giá có sẵn"},
        404: {"model": ErrorResponse, "description": "message_id không tồn tại"},
        422: {"model": ErrorResponse, "description": "Chỉ đánh giá được tin nhắn của assistant"},
    },
)
def create_feedback(body: FeedbackCreate, response: Response, db: Session = Depends(get_db)) -> FeedbackOut:
    msg = db.get(Message, body.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn")
    if msg.role != MessageRole.assistant:
        raise HTTPException(status_code=422, detail="Chỉ đánh giá được tin nhắn của assistant")

    rating = 1 if body.rating == "up" else -1
    fb = msg.feedback
    if fb is None:
        fb = Feedback(message_id=msg.id, rating=rating, comment=body.comment)
        db.add(fb)
    else:
        fb.rating = rating
        fb.comment = body.comment
        response.status_code = 200
    db.commit()
    db.refresh(fb)
    return feedback_out(fb)

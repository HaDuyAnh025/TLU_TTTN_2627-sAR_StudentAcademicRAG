"""Xử lý POST /chat ở chế độ MOCK (T3-08).

Câu trả lời và nguồn trích dẫn là dữ liệu giả lập, nhưng được lưu vào DB y như thật
(conversations, messages, citations) để Web UI và luồng feedback làm được ngay từ tuần 3.
T4-08 sẽ thay `_generate_mock` bằng: retriever -> prompt (T4-04) -> LLM (T4-05).
"""

import time
import uuid

from sqlalchemy.orm import Session

from app.db.models import Citation, Conversation, Message, MessageRole, utcnow
from app.schemas.api import ChatRequest

MOCK_MODEL = "mock-v1"

# Nguồn giả lập lấy từ dữ liệu thật đã crawl (crawl_2/crawl_v2.json) để hiển thị cho giống.
_MOCK_SOURCES = [
    {
        "chunk_id": "tb-2281#mock-0",
        "doc_id": "tb-2281",
        "title": "QUYẾT ĐỊNH Ban hành Quy chế đào tạo trình độ đại học của Trường Đại học Thăng Long",
        "source_url": "https://thanglong.edu.vn/vi/thong-bao/2281",
        "snippet": "Quy chế quy định về tổ chức đào tạo, đăng ký học tập, đánh giá kết quả học tập "
        "và xét công nhận tốt nghiệp trình độ đại học...",
        "score": 0.82,
        "metadata": {"category": "quy_che", "issued_date": "2026-08-20"},
    },
    {
        "chunk_id": "tb-2248#mock-0",
        "doc_id": "tb-2248",
        "title": "QUYẾT ĐỊNH V/v Ban hành mức thu học phí đại học chính quy năm học 2026 - 2027",
        "source_url": "https://thanglong.edu.vn/vi/thong-bao/2248",
        "snippet": "Mức thu học phí đại học chính quy năm học 2026 - 2027 được tính theo số tín chỉ "
        "sinh viên đăng ký...",
        "score": 0.74,
        "metadata": {"category": "hoc_phi", "issued_date": "2026-07-09"},
    },
    {
        "chunk_id": "tb-2277#mock-0",
        "doc_id": "tb-2277",
        "title": "THÔNG BÁO Đăng ký học học kỳ I năm học 2026 - 2027 dành cho sinh viên khoá từ 32",
        "source_url": "https://thanglong.edu.vn/vi/thong-bao/2277",
        "snippet": "Sinh viên đăng ký học qua Cổng thông tin sinh viên theo lịch của từng khóa...",
        "score": 0.69,
        "metadata": {"category": "quy_che", "issued_date": "2026-08-17"},
    },
]


def _generate_mock(question: str, top_k: int) -> tuple[str, list[dict]]:
    sources = _MOCK_SOURCES[: min(top_k, len(_MOCK_SOURCES))]
    refs = " ".join(f"[{i}]" for i in range(1, len(sources) + 1))
    answer = (
        f'[MOCK] Đây là câu trả lời giả lập cho câu hỏi: "{question}".\n\n'
        "Khi hệ thống RAG hoàn thiện (tuần 4), câu trả lời sẽ được sinh từ các văn bản "
        f"học vụ của Trường Đại học Thăng Long và trích dẫn nguồn như sau {refs}."
    )
    return answer, sources


class ConversationNotFound(LookupError):
    pass


def handle_chat(db: Session, req: ChatRequest) -> tuple[Conversation, Message]:
    started = time.perf_counter()

    if req.conversation_id is not None:
        conv = db.get(Conversation, req.conversation_id)
        if conv is None:
            raise ConversationNotFound(str(req.conversation_id))
    else:
        conv = Conversation(id=uuid.uuid4(), user_id=req.user_id, title=req.message[:80])
        db.add(conv)

    user_msg = Message(conversation=conv, role=MessageRole.user, content=req.message)
    db.add(user_msg)
    db.flush()

    answer, sources = _generate_mock(req.message, req.top_k)
    assistant_msg = Message(
        conversation=conv,
        role=MessageRole.assistant,
        content=answer,
        model=MOCK_MODEL,
        extra={"mode": "mock", "filters": req.filters.model_dump() if req.filters else None},
        citations=[
            Citation(
                rank=i,
                chunk_id=s["chunk_id"],
                doc_id=s["doc_id"],
                title=s["title"],
                source_url=s["source_url"],
                snippet=s["snippet"],
                score=s["score"],
                extra=s["metadata"],
            )
            for i, s in enumerate(sources, start=1)
        ],
    )
    assistant_msg.latency_ms = int((time.perf_counter() - started) * 1000)
    db.add(assistant_msg)
    conv.updated_at = utcnow()
    db.commit()
    db.refresh(assistant_msg)
    return conv, assistant_msg

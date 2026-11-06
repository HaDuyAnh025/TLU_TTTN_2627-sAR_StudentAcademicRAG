"""Điểm khởi động FastAPI. Chạy: uvicorn app.main:app --reload (trong thư mục backend/)."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, conversations, feedback, health, search, suggestions
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DESCRIPTION = """
API cho hệ thống hỏi đáp học vụ **sAR - Student Academic RAG** (Trường ĐH Thăng Long).

* `POST /chat`: hỏi đáp (tuần 3 trả câu trả lời **mock**, đã lưu DB thật)
* `GET /conversations/{id}`: lịch sử hội thoại
* `POST /feedback`: đánh giá câu trả lời
* `GET /suggestions`: câu hỏi gợi ý
* `GET /search`: tìm kiếm **thật** trên Qdrant (bọc retriever của nhóm AI)
"""


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=s.app_version, description=DESCRIPTION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    for r in (chat.router, conversations.router, feedback.router, suggestions.router, search.router):
        app.include_router(r, prefix=s.api_prefix)
    return app


app = create_app()

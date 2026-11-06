"""Cấu hình ứng dụng, đọc từ biến môi trường hoặc file .env (xem .env.example ở gốc repo)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Chạy trong thư mục backend/ hoặc ở gốc repo đều đọc được .env
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ứng dụng ---
    app_name: str = "sAR - Student Academic RAG API"
    app_version: str = "0.1.0"
    environment: str = "dev"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # --- PostgreSQL ---
    database_url: str = "postgresql+psycopg://sar:sar_password@localhost:5432/sar"

    # --- Redis (để trống REDIS_URL thì tắt cache) ---
    redis_url: str | None = "redis://localhost:6379/0"
    search_cache_ttl: int = 300

    # --- Qdrant (QDRANT_URL=":memory:" để chạy trong bộ nhớ, dùng cho test) ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "sar_chunks"

    # --- Embedding: PHẢI trùng với mô hình dùng khi index (T3-03 / T3-05) ---
    embedding_provider: Literal["sentence_transformers", "hash"] = "sentence_transformers"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384  # chỉ dùng cho provider "hash"
    embedding_query_prefix: str = "query: "  # e5 cần tiền tố; BGE-M3 / SBERT để trống
    embedding_passage_prefix: str = "passage: "

    # --- Tìm kiếm ---
    search_default_top_k: int = 5
    search_max_top_k: int = 20

    # --- Chat: hiện chỉ có "mock" (T3-08); T4-08 sẽ thêm "rag" ---
    chat_mode: Literal["mock"] = "mock"
    mock_stream_delay_ms: int = 30  # độ trễ giữa các token khi stream mock (để UI thấy hiệu ứng gõ)


@lru_cache
def get_settings() -> Settings:
    return Settings()

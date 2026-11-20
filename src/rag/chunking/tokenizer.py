"""Đếm token bằng tiktoken (cl100k_base), tương thích text-embedding-3-small."""
from __future__ import annotations

from functools import lru_cache

import tiktoken

from rag.config import chunking_config


@lru_cache(maxsize=1)
def _enc() -> tiktoken.Encoding:
    cfg = chunking_config()  # đặt TIKTOKEN_CACHE_DIR trước khi nạp vocab
    return tiktoken.get_encoding(cfg["encoding"])


def count_tokens(text: str) -> int:
    """Số token của văn bản."""
    return len(_enc().encode(text))

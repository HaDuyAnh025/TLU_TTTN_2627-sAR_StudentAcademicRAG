"""Câu hỏi gợi ý hiển thị ở màn hình chat (GET /suggestions).

Hiện lấy từ file tĩnh app/data/suggestions.json. Sau này có thể sinh từ các câu hỏi được
hỏi nhiều / được feedback "up" nhiều trong bảng messages.
"""

import json
from functools import lru_cache
from itertools import zip_longest
from pathlib import Path

from app.schemas.api import Suggestion

_FILE = Path(__file__).resolve().parent.parent / "data" / "suggestions.json"


@lru_cache
def _load() -> tuple[Suggestion, ...]:
    with _FILE.open(encoding="utf-8") as f:
        return tuple(Suggestion(**x) for x in json.load(f))


def get_suggestions(limit: int, category: str | None = None) -> list[Suggestion]:
    items = _load()
    if category:
        return [s for s in items if s.category == category][:limit]
    # Không lọc: lấy xen kẽ từng nhóm để gợi ý đa dạng chủ đề
    groups: dict[str, list[Suggestion]] = {}
    for s in items:
        groups.setdefault(s.category, []).append(s)
    mixed = [s for row in zip_longest(*groups.values()) for s in row if s is not None]
    return mixed[:limit]

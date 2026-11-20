"""Dựng breadcrumb `[Tài liệu > Chương > Điều > Khoản]` cho embed_text của C2/C3."""
from __future__ import annotations

MAX_TITLE_CHARS = 160
MAX_TABLE_TITLE_WORDS = 20  # tiêu đề bảng trong breadcrumb: tối đa ngần này từ (metadata.table_title giữ bản đầy đủ)


def short_title(title: str | None) -> str:
    """Rút gọn tiêu đề tài liệu để breadcrumb không quá dài."""
    t = (title or "tài liệu").strip()
    return t if len(t) <= MAX_TITLE_CHARS else t[: MAX_TITLE_CHARS - 1].rstrip() + "…"


def make_breadcrumb(title: str | None, *parts: str | None) -> str:
    """`[title > part1 > part2 ...]`, bỏ phần rỗng."""
    return "[" + " > ".join([short_title(title), *[p for p in parts if p]]) + "]"


def short_table_title(title: str | None, max_words: int = MAX_TABLE_TITLE_WORDS) -> str | None:
    """Tiêu đề bảng cho breadcrumb: quá `max_words` từ thì cắt ở ranh giới từ và thêm "…"."""
    if not title:
        return title
    words = title.split()
    return title if len(words) <= max_words else " ".join(words[:max_words]) + "…"

"""Chuẩn hóa văn bản trước khi cắt: NFC, gộp khoảng trắng, gộp dòng trống."""
from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"[ \t\u00a0]+")
_BLANKS = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """NFC, bỏ \r, gộp khoảng trắng liên tiếp, bỏ khoảng trắng cuối dòng, tối đa 1 dòng trống liên tiếp."""
    t = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    t = _SPACES.sub(" ", t)
    t = "\n".join(line.strip() if line.strip() == "" else line.rstrip() for line in t.split("\n"))
    return _BLANKS.sub("\n\n", t).strip()

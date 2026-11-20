"""Giao diện chung của parser: văn bản (đã lọc thủ tục) -> danh sách Section theo thứ tự."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Section:
    """Một đơn vị cấu trúc. start/end theo tọa độ văn bản đã lọc (ftext)."""

    kind: str  # preamble | article | lead | clause | text
    start: int
    end: int
    key: str  # phần id cấu trúc, ví dụ "d12::k2"
    parent_key: str  # đơn vị cha: chỉ gộp chunk nhỏ trong cùng parent_key
    chapter: str | None = None
    chapter_title: str | None = None
    article: int | None = None
    article_title: str | None = None
    clause: int | None = None
    is_preamble: bool = False
    fallback: bool = False
    point: str | None = None
    article_key: str | None = None  # khóa Điều (d12, hoặc b2::d1 khi số Điều đánh số lại) -> parent_id
    nganh_ma: str | None = None  # mục tờ rơi theo trang: ngành của trang
    nganh_ten: str | None = None
    nganh_ma_goc: str | None = None
    crumb: list[str] | None = None  # breadcrumb tùy chỉnh (parser mục/heading); None = dựng từ chapter/article/clause


class BaseParser(Protocol):
    """Mọi parser theo doc_type dùng chung giao diện này."""

    def parse(self, ftext: str, preamble: tuple[int, int] | None = None) -> list[Section]:
        """Tách ftext thành các Section liền kề theo thứ tự xuất hiện."""
        ...

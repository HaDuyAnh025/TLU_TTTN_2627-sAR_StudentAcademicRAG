"""Parser theo heading cho tài liệu KHÔNG có "Điều N." (thong_bao, ke_hoach, lich_thi, tkb, hoc_phi dạng thông báo...).

Nhận diện heading theo thứ tự ưu tiên: dòng viết hoa toàn bộ, mục La Mã (I., II.), mục số (1., 1.1.), mục chữ (a), b)).
Mỗi heading mở một Section; breadcrumb = tiêu đề văn bản > heading cha > heading hiện tại. Gạch đầu dòng chỉ dùng khi
phải chia phần dài (xem splitter). Dòng của bảng Markdown (bắt đầu bằng `|`) không bao giờ là heading.
"""
from __future__ import annotations

import re

from ..procedural import SIGN
from .base import Section

RE_ROMAN = re.compile(r"^\s*([IVX]+)\.\s+(\S.*)$")
RE_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
RE_LETTER = re.compile(r"^\s*([a-zđ])\)\s+(\S.*)$")
MAX_HEADING_CHARS = 100
RE_LABEL_ONLY = re.compile(r"^\s*([A-ZĐ]|[IVX]+|\d+(?:\.\d+)*)\.\s*$")
RE_LETTER_UP = re.compile(r"^\s*[A-ZĐ]\.\s+\S")


def heading_of(line: str) -> tuple[int, str] | None:
    """(cấp, tên heading) nếu dòng là heading, ngược lại None. Cấp 1: viết hoa/La Mã; 2: "1."; 3: "1.1."; 4: "a)"."""
    s = line.strip()
    if not s or s.startswith("|") or len(s) > MAX_HEADING_CHARS:
        return None
    if SIGN.match(s) and s.upper() == s and len(s) <= 40:
        return None
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and s.upper() == s and not s.endswith((".", ";", ",")):
        return 1, s
    if s.endswith((".", ";", ",")):
        return None
    if RE_ROMAN.match(s) or RE_LETTER_UP.match(s):
        return 1, s
    m = RE_NUM.match(s)
    if m and not re.match(r"^\d+\s*$", s):
        return (2 if "." not in m.group(1) else 3), s
    if RE_LETTER.match(s):
        return 4, s
    return None


class StructuredParser:
    """Tách theo heading; `found` cho biết có tìm thấy heading nào không (để quyết định fallback)."""

    def __init__(self) -> None:
        self.found = False

    def parse(self, ftext: str, preamble: tuple[int, int] | None = None) -> list[Section]:
        marks: list[tuple[int, int, str]] = []  # (vị trí, cấp, tên)
        pos = 0
        lines = ftext.split("\n")
        pending: tuple[int, str] | None = None  # nhãn đứng riêng ("A.") chờ dòng tiêu đề kế tiếp
        for l in lines:
            start, pos = pos, pos + len(l) + 1
            if preamble and preamble[0] <= start < preamble[1]:
                continue
            if pending:
                if l.strip():
                    h = heading_of(pending[1] + " " + l.strip())
                    if h:
                        marks.append((pending[0], h[0], h[1]))
                    pending = None
                    if h:
                        continue
                else:
                    continue
            if RE_LABEL_ONLY.match(l):
                pending = (start, l.strip())
                continue
            h = heading_of(l)
            if h:
                marks.append((start, h[0], h[1]))
        self.found = bool(marks)
        out: list[Section] = []
        lo = 0
        if preamble:
            out.append(Section("preamble", preamble[0], preamble[1], "preamble", "preamble", is_preamble=True))
            lo = preamble[1]
        first = marks[0][0] if marks else len(ftext)
        first = max(first, lo)
        if ftext[lo:first].strip():
            out.append(Section("text", lo, first, "s000", "s000", crumb=[]))
        stack: list[tuple[int, str, str]] = []  # (cấp, tên, key)
        for i, (start, level, name) in enumerate(marks):
            if start < lo:
                continue
            end = marks[i + 1][0] if i + 1 < len(marks) else len(ftext)
            while stack and stack[-1][0] >= level:
                stack.pop()
            key = f"s{i + 1:03d}"
            stack.append((level, name, key))
            parent = stack[0][2]  # heading cấp cao nhất đang mở
            out.append(Section("section", start, end, key, parent, crumb=[n for _, n, _ in stack]))
        return out

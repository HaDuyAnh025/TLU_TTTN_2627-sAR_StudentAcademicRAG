"""Tách bảng Markdown (`| a | b |` + dòng `|---|---|`) khỏi văn bản tài liệu, giữ vị trí ký tự.

Chỉ nhận bảng có dòng phân cách `|---|`; khối dòng `|` của trang OCR (không có dòng phân cách) KHÔNG được coi là bảng.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
TITLE_MAX_WORDS = 15  # chú thích bảng: tối đa ngần này từ
TITLE_RE = re.compile(r"^\s*(bảng|biểu|phụ lục|danh sách|mẫu)\b", re.I)
NOTE_RE = re.compile(r"^\s*(ghi chú|chú thích|lưu ý|nguồn\s*:|\(\*+\)|\*+\s|\(\d+\))", re.I)
ARTICLE_RE = re.compile(r"^\s*(điều\s+\d+|chương\s+[ivxlc\d]+)\b", re.I)


@dataclass
class Row:
    """Một dòng dữ liệu đã chuẩn hóa. `start`/`end`: vị trí dòng gốc trong văn bản."""

    cells: list[str]
    start: int
    end: int
    label: str | None = None  # dòng nhãn nhóm (một ô duy nhất) đứng trước


@dataclass
class Table:
    """Bảng đã tách. Vị trí theo tọa độ văn bản truyền vào `find_tables`."""

    start: int
    end: int
    header: list[str]
    rows: list[Row]
    raw_header_line: str = ""
    fill_cols: list[int] = field(default_factory=list)
    title: str | None = None
    lead_in: str | None = None
    note: str | None = None
    excluded: list[tuple[int, int]] = field(default_factory=list)  # vùng văn bản thuộc bảng (tiêu đề, câu dẫn, bảng, ghi chú)
    note_span: tuple[int, int] | None = None
    promoted: str | None = None  # nhãn lấy từ dòng đầu bảng chỉ có 1 ô (đã đưa lên làm tiêu đề, bị xóa khỏi bảng)
    raw_text: str | None = None  # văn bản bảng dựng lại (header = dòng kế tiếp + dòng phân cách mới) khi có dòng 1 ô bị đưa lên làm tiêu đề


def split_row(line: str) -> list[str]:
    """Tách dòng bảng Markdown thành các ô (đã strip)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _line_spans(text: str, lo: int, hi: int) -> list[tuple[int, int, str]]:
    out, pos = [], lo
    for l in text[lo:hi].split("\n"):
        out.append((pos, pos + len(l), l))
        pos += len(l) + 1
    return out


def find_tables(text: str, lo: int = 0, hi: int | None = None) -> list[tuple[int, int, list[tuple[int, int, str]]]]:
    """Các khối bảng: (start, end, [(line_start, line_end, line)]) gồm cả dòng header và dòng phân cách."""
    hi = len(text) if hi is None else hi
    lines = _line_spans(text, lo, hi)
    out, i = [], 0
    while i < len(lines):
        if lines[i][2].lstrip().startswith("|") and i + 1 < len(lines) and SEP.match(lines[i + 1][2]):
            j = i + 2
            while j < len(lines) and lines[j][2].lstrip().startswith("|"):
                j += 1
            out.append((lines[i][0], lines[j - 1][1], lines[i:j]))
            i = j
        else:
            i += 1
    return out


def context_of(text: str, start: int, end: int, lo: int, hi: int, generic: bool = True) -> dict:
    """Tiêu đề bảng, câu dẫn phía trước và ghi chú phía sau (kèm vùng ký tự để loại khỏi đoạn văn bản thường)."""
    before = [(s, e, l) for s, e, l in _line_spans(text, lo, start) if l.strip()]
    ctx: dict = {"title": None, "lead": None, "excluded": [], "note": None, "note_span": None}
    if before:
        s1, e1, l1 = before[-1]
        if TITLE_RE.match(l1) and len(l1) <= 200:
            ctx["title"] = l1.strip()
            ctx["excluded"].append((s1, e1))
            if len(before) >= 2 and before[-2][2].rstrip().endswith(":"):
                s0, e0, l0 = before[-2]
                ctx["lead"] = l0.strip()
                ctx["excluded"].append((s0, e0))
        elif l1.rstrip().endswith(":"):
            ctx["lead"] = l1.strip()
            ctx["excluded"].append((s1, e1))
    if generic and ctx["title"] is None and ctx["lead"] is None and before:
        s1, e1, l1 = before[-1]
        stripped = l1.strip()
        if stripped.startswith("|"):  # dòng "| nhãn |" lẻ (không thuộc bảng nào): lấy chữ trong ô duy nhất
            cells = [c for c in split_row(stripped) if c]
            stripped = cells[0] if len(cells) == 1 else ""
        words = stripped.split()
        gap = text[e1:start]
        if stripped and 1 <= len(words) <= TITLE_MAX_WORDS and gap.count("\n") <= 2 and not gap.strip() and re.search(r"[^\W\d_]", stripped):
            ctx["title"] = stripped  # chú thích bảng: dòng ngắn nằm sát trước bảng (cách tối đa 1 dòng trống), không còn là chunk chữ riêng
            ctx["excluded"].append((s1, e1))
    after = _line_spans(text, end + 1, hi) if end + 1 < hi else []
    k = 0
    while k < len(after) and not after[k][2].strip() and k < 1:
        k += 1
    if k < len(after) and NOTE_RE.match(after[k][2]):
        ns = after[k][0]
        ne = after[k][1]
        m = k + 1
        while m < len(after) and after[m][2].strip() and not after[m][2].lstrip().startswith("|") and not ARTICLE_RE.match(after[m][2]):
            ne = after[m][1]
            m += 1
        ctx["note"] = re.sub(r"\s+", " ", text[ns:ne]).strip()
        ctx["note_span"] = (ns, ne)
        ctx["excluded"].append((ns, ne))
    return ctx

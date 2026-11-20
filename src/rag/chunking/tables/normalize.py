"""Chuẩn hóa bảng: gộp header nhiều tầng, fill-down ô gộp (rowspan), bỏ dòng trống/lặp, nhận dòng nhãn nhóm."""
from __future__ import annotations

import re

from .extract import SEP, Row, Table, context_of, find_tables, split_row

NUMLIKE = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d{4,}|^\s*[\d.,%]+\s*$")  # ô số liệu (tiền, số lớn)
HAS_DIGIT = re.compile(r"\d")
HAS_LETTER = re.compile(r"[A-Za-zÀ-ỹ]")
NOTE_HEADER = re.compile(r"ghi chú|lưu ý|điều kiện|nội dung|mô tả|diễn giải|ghi\b", re.I)


def _lower_first(s: str) -> str:
    return s if len(s) > 1 and s[1].isupper() else s[:1].lower() + s[1:]


def merge_header(tiers: list[list[str]], n: int) -> list[str]:
    """Gộp header nhiều tầng thành 1 tầng: "Học phí" + "Chính quy" -> "Học phí chính quy". Tầng trên: ô trống = colspan, điền từ trái."""
    filled = []
    for t, row in enumerate(tiers):
        r = (row + [""] * n)[:n]
        if t < len(tiers) - 1:
            last = ""
            for i, c in enumerate(r):
                if c:
                    last = c
                else:
                    r[i] = last
        filled.append(r)
    out = []
    for i in range(n):
        parts: list[str] = []
        for r in filled:
            c = re.sub(r"\s+", " ", r[i]).strip()
            if c and (not parts or c.lower() != parts[-1].lower()):
                parts.append(c if not parts else _lower_first(c))
        out.append(" ".join(parts) or f"Cột {i + 1}")
    return out


NUMLIKE = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d{4,}|^\s*[\d.,%]+\s*$")


def _is_subheader(cells: list[str], nxt: list[str] | None) -> bool:
    """Dòng header tầng 2: có chữ, không ô nào là số/tiền (ô như "Năm 1 (kỳ 1-2)" vẫn là header); dòng sau có ô số."""
    ne = [c for c in cells if c]
    return bool(ne) and not any(NUMLIKE.search(c) for c in ne) and nxt is not None and any(NUMLIKE.search(c) for c in nxt)


def build_table(text: str, block: tuple, lo: int, hi: int) -> Table:
    """Dựng Table chuẩn hóa từ một khối bảng thô (kết quả của find_tables) và ngữ cảnh xung quanh trong [lo, hi)."""
    start, end, lines = block
    header_cells = split_row(lines[0][2])
    raw = [(split_row(l), s, e) for s, e, l in lines[2:]]
    n = max([len(header_cells)] + [len(c) for c, _, _ in raw])
    promoted = None  # dòng tiêu đề chỉ có 1 ô có chữ (các ô còn lại trống, bảng >= 3 cột): đó là nhãn/tiêu đề bảng, dòng kế tiếp mới là header
    raw_text = None
    # CHỈ áp dụng cho dòng ĐẦU TIÊN của bảng (dòng 1 ô ở giữa bảng là nhãn nhóm, giữ nguyên) và khi dòng kế tiếp không phải dòng số liệu
    if n >= 3 and sum(1 for c in header_cells if c) == 1 and raw and not any(NUMLIKE.search(c) for c in raw[0][0]):
        promoted = next(c for c in header_cells if c)
        header_cells = (raw[0][0] + [""] * n)[:n]
        raw = raw[1:]
        raw_text = "\n".join([lines[2][2], "|" + "---|" * n] + [l for _, _, l in lines[3:]])  # bỏ dòng 1 ô + phân cách cũ; dựng phân cách mới
    tiers = [header_cells]
    k = 0
    while k < 2 and k < len(raw) and _is_subheader((raw[k][0] + [""] * n)[:n], (raw[k + 1][0] if k + 1 < len(raw) else None)):
        tiers.append((raw[k][0] + [""] * n)[:n])
        k += 1
    header = merge_header(tiers, n)
    data = [((c + [""] * n)[:n], s, e) for c, s, e in raw[k:]]
    # bỏ dòng trống, dòng lặp lại header, dòng trùng liên tiếp
    hnorm = [h.lower() for h in header]
    kept, prev = [], None
    for c, s, e in data:
        if not any(c):
            continue
        if [x.lower() for x in c] == hnorm or [x.lower() for x in c] == [x.lower() for x in header_cells + [""] * (n - len(header_cells))]:
            continue
        if prev == c:
            continue
        kept.append((c, s, e))
        prev = c
    # dòng nhãn nhóm: đúng 1 ô có chữ, bảng >= 3 cột
    rows: list[Row] = []
    label = None
    for c, s, e in kept:
        ne = [x for x in c if x]
        if n >= 3 and len(ne) == 1 and not HAS_DIGIT.search(ne[0]):
            label = ne[0]
            continue
        rows.append(Row(list(c), s, e, label))
    # cột fill-down: thưa (<70% có giá trị), có chữ, không phải cột ghi chú
    fill_cols = []
    for i in range(n):
        vals = [r.cells[i] for r in rows]
        frac = sum(1 for v in vals if v) / max(1, len(vals))
        if 0 < frac < 0.7 and any(HAS_LETTER.search(v) for v in vals) and not NOTE_HEADER.search(header[i]) and len(vals) > 1:
            fill_cols.append(i)
    for i in fill_cols:
        cur = ""
        for r in rows:
            if r.cells[i]:
                cur = r.cells[i]
            elif cur and sum(1 for x in r.cells if x) >= 1:
                r.cells[i] = cur
    ctx = context_of(text, start, end, lo, hi, generic=promoted is None)  # có nhãn trong bảng thì không lấy dòng chữ phía trước làm tiêu đề
    title = (f"{ctx['title']} – {promoted}" if ctx["title"] else promoted) if promoted else ctx["title"]
    t = Table(start, end, header, rows, lines[0][2], fill_cols, title, ctx["lead"], ctx["note"], ctx["excluded"] + [(start, end)], ctx["note_span"],
              promoted, raw_text)
    return t


def tables_in(text: str, lo: int, hi: int) -> list[Table]:
    """Các bảng nằm hoàn toàn trong [lo, hi) kèm ngữ cảnh."""
    return [build_table(text, b, lo, hi) for b in find_tables(text, lo, hi)]

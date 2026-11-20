"""Quy tắc bảng: bảng nhỏ giữ nguyên (1 chunk); bảng lớn chia nhóm/dòng, lặp header, mỗi dòng thành 1 câu."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..tokenizer import count_tokens
from .extract import Row, Table
from .templates import SPECS, resolve, row_sentence

log = logging.getLogger("chunking")


@dataclass
class TableChunk:
    """Chunk bảng (hoặc ghi chú dài của bảng) chưa gắn breadcrumb. `body` là phần đứng sau breadcrumb trong embed_text."""

    kind: str  # whole | rows | note
    table_no: int
    start: int  # tọa độ văn bản truyền vào
    end: int
    body: str
    content: str
    row_start: int | None = None
    row_end: int | None = None
    n_rows: int = 0
    oversize: bool = False
    suffix: str = ""  # "::c1", "::c2"... khi một dòng quá dài được tách theo nhóm cột


def _md(header: list[str], rows: list[Row]) -> str:
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    lines = ["| " + " | ".join(esc(h) for h in header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(esc(c) for c in r.cells) + " |" for r in rows]
    return "\n".join(lines)


ID_FIELDS = ("ten", "ma", "lop", "loai", "he")


def _id_cols(doc_type: str, header: list[str], row: Row) -> list[int]:
    """Cột định danh lặp lại ở mọi mảnh của một dòng quá dài: cột đầu + cột tên/mã (nếu có và khác cột đầu)."""
    ids = [0]
    cols = resolve(doc_type, header)
    for f in ID_FIELDS:
        if f in cols and cols[f] not in ids and row.cells[cols[f]]:
            ids.append(cols[f])
            break
    if len(ids) < 2:  # doc_type không có template: nhận cột theo tên header ("Tên ...", "Mã ...")
        for i, h in enumerate(header):
            if i not in ids and row.cells[i] and re.match(r"^\s*(tên|mã)", h, re.I):
                ids.append(i)
                break
    return ids[:2]


def _split_row(t: Table, k: int, table_no: int, doc_type: str, crumb: str, lead: str, note_part: str, max_tokens: int) -> list[TableChunk]:
    """Tách một dòng > max_tokens thành các mảnh theo nhóm cột liên tiếp; mỗi mảnh lặp header + giá trị cột định danh."""
    row = t.rows[k]
    ids = [i for i in _id_cols(doc_type, t.header, row) if count_tokens(row.cells[i]) <= 40 and True]
    rest = [i for i in range(len(t.header)) if i not in ids and row.cells[i]]
    prefix = f"{row.label}: " if row.label else ""
    lab = {i: (h if count_tokens(h) <= 30 else f"Cột {i + 1}") for i, h in enumerate(t.header)}  # header quá dài (thực ra là dòng dữ liệu) -> nhãn cột

    if any(l != t.header[i] for i, l in lab.items()):
        log.info("HEADER_THAY_COT bảng %d (dòng %d): header quá dài, đổi thành 'Cột n' ở các mảnh của dòng", table_no, k)

    def render(cols: list[int], vals: dict[int, str]) -> str:
        head = "Các cột: " + " | ".join(lab[i] for i in cols) + ". "
        return f"{lead}{head}{prefix}" + "; ".join(f"{lab[i]}: {vals[i]}" for i in cols if vals.get(i)) + "." + note_part

    def fits(cols: list[int], vals: dict[int, str]) -> bool:
        return count_tokens(f"{crumb} {render(cols, vals)}") <= max_tokens

    base = {i: row.cells[i] for i in range(len(t.header))}
    groups: list[tuple[list[int], dict[int, str], list[int]]] = []
    cur: list[int] = []
    for c in rest:
        if fits(ids + cur + [c], base):
            cur.append(c)
            continue
        if cur:
            groups.append((cur, base, ids))
            cur = []
        if fits(ids + [c], base):
            cur = [c]
            continue
        words, part = base[c].split(), []  # một ô quá dài: cắt theo từ (mảnh đứng riêng, vẫn kèm cột định danh nếu còn chỗ)
        keep = ids if fits(ids + [c], {**base, c: words[0]}) else []
        for w in words:
            if part and not fits(keep + [c], {**base, c: " ".join(part + [w])}):
                groups.append(([c], {**base, c: " ".join(part)}, keep))
                part = []
            part.append(w)
        if part:
            groups.append(([c], {**base, c: " ".join(part)}, keep))
    if cur or not groups:
        groups.append((cur, base, ids))
    out = []
    for n, (cols, vals, idc) in enumerate(groups, 1):
        sel = idc + cols
        body = render(sel, vals)
        sub = Row([vals[i] for i in sel], row.start, row.end, row.label)
        out.append(TableChunk("rows", table_no, row.start, row.end, body, _md([lab[i] for i in sel], [sub]), k, k, 1,
                              count_tokens(f"{crumb} {body}") > max_tokens, f"::c{n}"))
    return out


def _groups(t: Table) -> list[list[int]]:
    """Gom chỉ số dòng liên tiếp theo nhóm logic (nhãn nhóm + giá trị các cột fill-down)."""
    keys = [(r.label, tuple(r.cells[i] for i in t.fill_cols)) for r in t.rows]
    out: list[list[int]] = []
    for i, k in enumerate(keys):
        if out and keys[out[-1][0]] == k:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def chunk_table(t: Table, table_no: int, text: str, doc_type: str, crumb: str, max_tokens: int, small_max: int, note_inline_max: int) -> list[TableChunk]:
    """Chia một bảng thành các TableChunk. `crumb` là breadcrumb đã gồm tên bảng; `text` là văn bản chứa bảng (để lấy nguyên văn)."""
    note = t.note
    note_tokens = count_tokens(note) if note else 0
    inline_note = note if note and note_tokens <= note_inline_max else None
    out: list[TableChunk] = []
    lead = (t.lead_in + " ") if t.lead_in else ""
    note_part = f" {inline_note}" if inline_note else ""
    raw = t.raw_text if t.raw_text is not None else text[t.start:t.end]

    whole_embed = f"{crumb} {lead}{raw}{note_part}"
    if count_tokens(whole_embed) <= min(small_max, max_tokens):
        out.append(TableChunk("whole", table_no, t.start, t.end, f"{lead}{raw}{note_part}", raw, 0, max(len(t.rows) - 1, 0), len(t.rows)))
    elif t.rows:
        header_line = "Các cột: " + " | ".join(t.header) + "."
        sents = [row_sentence(doc_type, t.header, r) for r in t.rows]
        stoks = [count_tokens(s) + 1 for s in sents]
        base = count_tokens(f"{crumb} {lead}{header_line}{note_part}")
        for grp in _groups(t):
            i = 0
            while i < len(grp):
                total, j = base, i
                while j < len(grp) and (j == i or total + stoks[grp[j]] <= max_tokens):
                    total += stoks[grp[j]]
                    j += 1
                while j - i > 1 and count_tokens(f"{crumb} {lead}{header_line} " + " ".join(sents[k] for k in grp[i:j]) + note_part) > max_tokens:
                    j -= 1  # đếm lại thật sự: tokenizer không cộng tính được
                idx = grp[i:j]
                body = f"{lead}{header_line} " + " ".join(sents[k] for k in idx) + note_part
                over = count_tokens(f"{crumb} {body}") > max_tokens
                if over:
                    log.debug("bảng %d: dòng %d vượt %d token dù chỉ có 1 dòng (không cắt giữa dòng)", table_no, idx[0], max_tokens)
                if over and len(idx) == 1:
                    out += _split_row(t, idx[0], table_no, doc_type, crumb, lead, note_part, max_tokens)
                    i = j
                    continue
                rows = [t.rows[k] for k in idx]
                out.append(TableChunk("rows", table_no, rows[0].start, rows[-1].end, body, _md(t.header, rows), idx[0], idx[-1], len(idx), over))
                i = j
    if note and not inline_note and t.note_span:
        out.append(TableChunk("note", table_no, t.note_span[0], t.note_span[1], note, text[t.note_span[0]:t.note_span[1]]))
    return out

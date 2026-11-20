"""Parser Chương > Điều > Khoản (> Điểm), dùng chung cho MỌI tài liệu có "Điều N." bất kể doc_type.

Điểm (a), b), ...) nằm trong Khoản; chỉ tách riêng khi Khoản vượt 512 token (xem splitter).
"""
from __future__ import annotations

import re

from .base import Section

RE_CHAPTER = re.compile(r"^\s*(?:CHƯƠNG|Chương)\s+([IVXLC]+|\d+)\b\s*[.:]?\s*(.*)$")
RE_ARTICLE = re.compile(r"^\s*Điều\s+(\d+)\s*[.:]\s*(.*)$")
RE_CLAUSE = re.compile(r"^\s*(\d+)\.(?!\d)\s*\S")
RE_ARTICLE_LINE = re.compile(r"^\s*Điều\s+\d+\s*[.:]", re.M)


def has_dieu(text: str) -> bool:
    """Tài liệu có ít nhất một dòng bắt đầu bằng "Điều N."."""
    return bool(RE_ARTICLE_LINE.search(text))


def article_title(rest: str) -> str | None:
    """Tiêu đề Điều nếu phần còn lại của dòng "Điều N." đủ ngắn và không phải câu nội dung (<= 12 từ, không dấu câu cuối)."""
    t = rest.strip()
    if not t or len(t.split()) > 12 or t.endswith((".", ":", ";", ",")) or ". " in t:
        return None
    return t


def in_span(span: tuple[int, int] | None, pos: int) -> bool:
    """pos nằm trong khoảng [span[0], span[1])."""
    return bool(span and span[0] <= pos < span[1])


class DieuParser:
    """Tách Chương/Điều/Khoản. Khoản chỉ nhận khi đánh số liên tiếp (1, 2, 3...) để tránh nhầm danh sách khác."""

    def parse(self, ftext: str, preamble: tuple[int, int] | None = None) -> list[Section]:
        n = len(ftext)
        marks: list[dict] = []
        chapter = chapter_title = None
        art_no: int | None = None
        block, last_art = 1, 0  # block tăng khi số Điều đánh số lại từ đầu (ví dụ Quyết định + Quy chế đính kèm)
        art_title: str | None = None
        clause_no = 0
        pend_title = False
        pos = 0
        for l in ftext.split("\n"):
            start, pos = pos, pos + len(l) + 1
            if not l.strip() or l.lstrip().startswith("|") or in_span(preamble, start):
                continue
            m = RE_CHAPTER.match(l)
            if m:
                chapter, chapter_title = m.group(1), m.group(2).strip() or None
                pend_title = chapter_title is None
                marks.append({"kind": "chapter", "start": start, "ctitle": chapter_title})
                continue
            if pend_title and not RE_ARTICLE.match(l):
                chapter_title = l.strip()
                marks[-1]["ctitle"] = chapter_title
                pend_title = False
                continue
            pend_title = False
            m = RE_ARTICLE.match(l)
            if m:
                art_no, art_title, clause_no = int(m.group(1)), article_title(m.group(2)), 0
                if art_no <= last_art:
                    block += 1
                last_art = art_no
                marks.append({"kind": "article", "start": start, "chapter": chapter, "ctitle": chapter_title,
                              "no": art_no, "title": art_title, "block": block})
                continue
            m = RE_CLAUSE.match(l)
            if m and art_no is not None and int(m.group(1)) == clause_no + 1:
                clause_no += 1
                marks.append({"kind": "clause", "start": start, "chapter": chapter, "ctitle": chapter_title,
                              "no": art_no, "title": art_title, "clause": clause_no, "block": block})
        out: list[Section] = []
        if preamble:
            out.append(Section("preamble", preamble[0], preamble[1], "preamble", "preamble", is_preamble=True))
        units = [m for m in marks if m["kind"] in ("article", "clause")]
        chapters = [m["start"] for m in marks if m["kind"] == "chapter"]
        first = units[0]["start"] if units else n
        lo = preamble[1] if preamble else 0
        first_stop = min([c for c in chapters if c >= lo] + [first])
        if ftext[lo:first_stop].strip():
            out.append(Section("text", lo, first_stop, "intro", "intro"))
        for i, m in enumerate(units):
            end = units[i + 1]["start"] if i + 1 < len(units) else n
            for c in chapters:  # dòng "Chương ..." đứng giữa không thuộc đơn vị hiện tại
                if m["start"] < c < end:
                    end = c
                    break
            a = m["no"]
            ak = f"d{a}" if m["block"] == 1 else f"b{m['block']}::d{a}"
            has_clause = i + 1 < len(units) and units[i + 1]["kind"] == "clause" and units[i + 1]["no"] == a
            if m["kind"] == "article":
                if not has_clause:
                    out.append(Section("article", m["start"], end, ak, ak, m["chapter"], m["ctitle"], a, m["title"], article_key=ak))
                else:
                    eol = ftext.find("\n", m["start"])
                    eol = n if eol == -1 else eol
                    if ftext[eol:end].strip():  # phần dẫn của Điều trước Khoản 1
                        out.append(Section("lead", m["start"], end, f"{ak}::lead", ak, m["chapter"], m["ctitle"], a, m["title"], article_key=ak))
            else:
                out.append(Section("clause", m["start"], end, f"{ak}::k{m['clause']}", ak, m["chapter"], m["ctitle"],
                                   a, m["title"], m["clause"], article_key=ak))
        return out

"""Điểm vào chunking: `chunk_corpus(config)` chạy C1/C2/C3 và ghi JSONL vào data/processed/.

Trạng thái: C1 và C2 đã chạy (Điều parser + parser heading). Quy tắc bảng (tables/), các parser đặc thù theo doc_type
và C3 sẽ thêm ở các bước sau. Khi chưa có tables/, bảng Markdown trong C2 chỉ được xử lý như văn bản thường.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from rag.config import chunking_config

from .breadcrumb import make_breadcrumb, short_table_title
from .fixed import fixed_windows
from .loader import Document, iter_documents
from .metadata import Chunk, ChunkMeta, DocMeta, load_doc_metas
from .parsers.base import Section
from .parsers.brochure import brochure_sections
from .programs import Catalog, ProgLabel, find_programs, program_at
from .parsers.dieu import DieuParser, has_dieu
from .parsers.generic import StructuredParser
from .procedural import FilterResult, filter_document
from .recursive import split_recursive
from .tables.chunker import TableChunk, chunk_table
from .tables.extract import Table
from .tables.normalize import tables_in
from .tokenizer import count_tokens

log = logging.getLogger("chunking")

POINT_LETTERS = "abcdđeghiklmnopqrstuvxy"
RE_POINT = re.compile(r"^\s*([a-zđ])\)\s*\S")
RE_NUMITEM = re.compile(r"^\s*\d+[.)]\s+\S")
RE_BULLET = re.compile(r"^\s*[-•–+]\s+\S")
STRUCTURED_TYPES = {"quy_che", "ctdt", "quy_trinh"}  # loại mà parser phải tìm được cấu trúc, nếu không -> fallback
DROP_LABELS = ["khung_hanh_chinh", "tieu_de", "dau_de_quyet_dinh", "so_roi_rac", "noi_nhan_chu_ky"]


def load_aliases(path: Path) -> dict[str, str]:
    """Đọc configs/aliases.yaml (viết tắt -> đầy đủ); không có file thì trả {}."""
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def find_aliases(text: str, aliases: dict[str, str]) -> list[str]:
    """Danh sách `viết tắt` và dạng đầy đủ của các từ viết tắt xuất hiện nguyên từ trong text."""
    out: list[str] = []
    for ab, full in aliases.items():
        if re.search(rf"(?<!\w){re.escape(ab)}(?!\w)", text):
            out += [ab, full]
    return out


def line_starts(text: str, s: int, e: int, rx: re.Pattern) -> list[int]:
    """Vị trí đầu các dòng trong text[s:e] khớp rx."""
    out, pos = [], s
    for line in text[s:e].split("\n"):
        if rx.match(line):
            out.append(pos)
        pos += len(line) + 1
    return out


@dataclass
class Unit:
    """Chunk trung gian của C2 (tọa độ ftext)."""

    sec: Section
    start: int
    end: int
    crumb_parts: list[str | None]
    piece: int | None = None  # None = nguyên đơn vị; 1.. = mảnh recursive
    merged_keys: list[str] | None = None
    tc: TableChunk | None = None  # chunk bảng (nếu có)
    table_title: str | None = None
    table_crumb: str | None = None


class Chunker:
    """Dựng chunk cho một cấu hình từ danh sách tài liệu."""

    def __init__(self, cfg: dict, metas: dict[str, DocMeta], aliases: dict[str, str]):
        self.cfg, self.metas, self.aliases = cfg, metas, aliases
        self.max_t, self.min_t = cfg["max_tokens"], cfg["min_tokens"]
        self._tno = 0
        self.catalog = Catalog.load(cfg.get("paths", {}).get("nganh"))  # configs/nganh.yaml (không có file thì không ghép)
        self.promoted_log: dict[tuple, dict] = {}  # (doc_id, vị trí bảng) -> bảng có dòng 1 ô đầu bảng đã đưa lên làm tiêu đề
        self._cur: tuple | None = None
        self.nganh_log: dict[tuple, dict] = {}  # (doc_id, tên gốc, mã gốc) -> dòng báo cáo ghép ngành
        self._progs: list = []
        self._last: tuple | None = None
        self.drop_rows: list[tuple[Document, DocMeta, FilterResult]] = []  # để xuất procedural_drop_report.csv

    # ---- metadata chung ------------------------------------------------------------------------------------------
    def _meta(self, doc: Document, dm: DocMeta, cs: int, ce: int, text_for_alias: str, **kw) -> ChunkMeta:
        ps, pe = doc.pages_for(cs, ce)
        base = dm.model_dump(exclude={"file", "do_chac", "can_kiem_tra", "ghi_chu_duyet", "trung_voi", "parser_mode"})
        base.update(char_start=cs, char_end=ce, page_start=ps, page_end=pe, text_routes=doc.routes_for(cs, ce),
                    aliases=find_aliases(text_for_alias, self.aliases), ocr_table_suspect=doc.ocr_table_suspect(cs, ce))
        base.update(kw)
        return ChunkMeta(**base)

    # ---- C1 ------------------------------------------------------------------------------------------------------
    def c1(self, doc: Document, dm: DocMeta) -> list[Chunk]:
        """Fixed-size 512/50, không breadcrumb, không lọc thủ tục."""
        out = []
        for i, (s, e) in enumerate(fixed_windows(doc.text, self.max_t, self.cfg["fixed_overlap"])):
            content = doc.text[s:e]
            out.append(Chunk(chunk_id=f"{doc.doc_id}::fx::{i + 1:04d}", config="c1", embed_text=content, content=content,
                             n_tokens=count_tokens(content), metadata=self._meta(doc, dm, s, e, content, chunk_index=i)))
        return out

    # ---- C2 ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _parser(ftext: str):
        """Điều parser nếu có "Điều N.", ngược lại parser theo heading."""
        return DieuParser() if has_dieu(ftext) else StructuredParser()

    @staticmethod
    def _crumb_parts(s: Section) -> list[str | None]:
        if s.is_preamble:
            return ["Căn cứ"]
        if s.crumb is not None:
            parts: list[str | None] = list(s.crumb)
        else:
            parts = []
            if s.chapter:
                parts.append(f"Chương {s.chapter}" + (f": {s.chapter_title}" if s.chapter_title else ""))
            if s.article is not None:
                parts.append(f"Điều {s.article}" + (f". {s.article_title}" if s.article_title else ""))
            if s.clause is not None:
                parts.append(f"Khoản {s.clause}")
        if s.point:
            parts.append(f"Điểm {s.point})")
        return parts

    def c2(self, doc: Document, dm: DocMeta) -> list[Chunk]:
        """Cấu trúc + breadcrumb + recursive dự phòng + gộp chunk nhỏ trong cùng đơn vị cha."""
        fr = filter_document(doc.text)
        if all(d.doc_id != doc.doc_id for d, _, _ in self.drop_rows[-1:]):
            self.drop_rows.append((doc, dm, fr))
        for w in fr.warnings:
            log.warning("%s: %s", doc.doc_id, w)
        title = dm.doc_heading or fr.heading or dm.title
        self._tno = 0
        if not fr.ftext.strip():
            return []
        if dm.parser_mode == "brochure_by_page":  # tờ rơi: mỗi trang một mục, không nhận dòng viết hoa làm heading
            blog: list = []
            parser, secs = None, brochure_sections(doc, fr, self.catalog, dm.bac_dao_tao, blog)
            self._log_matches(doc.doc_id, blog)
        else:
            parser = self._parser(fr.ftext)
            secs = parser.parse(fr.ftext, fr.preamble)
        # quy_che/ctdt/quy_trinh: fallback chỉ khi parser heading cũng không tìm được mục nào (quy định chia theo mục "1.", "-" vẫn là có cấu trúc)
        numbered = len(line_starts(fr.ftext, 0, len(fr.ftext), RE_NUMITEM)) >= 2  # chia theo mục số "1.", "2." (câu dài, không phải heading)
        missing = dm.doc_type in STRUCTURED_TYPES and isinstance(parser, StructuredParser) and not parser.found and not numbered
        if not secs and parser is None:
            return []
        if not secs:
            secs = [Section("text", 0, len(fr.ftext), "body", "body", crumb=[])]
            missing = missing or dm.doc_type in STRUCTURED_TYPES
        if missing:
            log.warning("%s (%s): không tìm được cấu trúc mong đợi -> fallback=true", doc.doc_id, dm.doc_type)
            for sec in secs:
                sec.fallback = True
        self._cur = (doc, fr, dm)
        self._progs = find_programs(fr.ftext, self.catalog, dm.bac_dao_tao) if dm.doc_type == "ctdt" and dm.parser_mode == "default" else []
        self._log_matches(doc.doc_id, [p.match for p in self._progs if p.match])
        self._last = (fr, secs, title)
        units = self._merge_small(fr, self._to_units(fr, secs, title, dm.doc_type), title)
        out: list[Chunk] = []
        for i, u in enumerate(units):
            ftxt = fr.ftext[u.start:u.end]
            cs, ce = fr.to_doc(u.start, u.end)
            keys = u.merged_keys or [u.sec.key]
            cid = f"{doc.doc_id}::" + "+".join(keys) + (f"::p{u.piece}" if u.piece else "")
            embed = f"{self._crumb(title, u)} {ftxt}"
            s = u.sec
            kw: dict = {}
            if u.tc is not None:
                tc = u.tc
                tid = f"{doc.doc_id}::t{tc.table_no}"
                if tc.oversize:
                    log.warning("%s: %s::r%s vượt %d token (dòng bảng đơn quá dài, không cắt giữa dòng)", doc.doc_id, tid, tc.row_start, self.max_t)
                cs, ce = fr.to_doc(tc.start, tc.end)
                embed, ftxt = f"{u.table_crumb} {tc.body}", tc.content
                if tc.kind == "note":
                    cid = f"{tid}::note"
                    kw = dict(table_id=tid, table_title=u.table_title)
                else:
                    cid = f"{tid}::r{tc.row_start:03d}-{tc.row_end:03d}{tc.suffix}"
                    kw = dict(is_table=True, table_id=tid, table_title=u.table_title, table_mode=tc.kind,
                              row_start=tc.row_start, row_end=tc.row_end)
            meta = self._meta(doc, dm, cs, ce, ftxt, chapter=s.chapter, article=s.article, clause=s.clause, point=s.point,
                              section=(s.crumb[-1] if s.crumb else None),
                              parent_id=(f"{doc.doc_id}::{s.article_key}" if s.article_key else None),
                              chunk_index=i, doc_heading=title, is_preamble=s.is_preamble, fallback=s.fallback, **self._nganh_kw(u), **kw)
            out.append(Chunk(chunk_id=cid, config="c2", embed_text=embed, content=ftxt, n_tokens=count_tokens(embed), metadata=meta))
        return self._unique(out)

    def _log_matches(self, doc_id: str, matches: list) -> None:
        """Ghi nhận kết quả ghép ngành (mỗi (doc, tên gốc, mã gốc) một dòng) để xuất bảng ghép cho người duyệt."""
        for m in matches:
            self.nganh_log.setdefault((doc_id, m.ten_goc, m.ma_goc), {"doc_id": doc_id, "ten_goc": m.ten_goc, "ma_goc": m.ma_goc or "",
                                                                    "ten_chuan": m.ten if m.cach not in ("chua_ghep", "ma_chua_co") else "", "ma": (m.ma or "") if m.cach not in ("chua_ghep", "ma_chua_co") else "",
                                                                    "cach_ghep": m.cach, "diem": m.diem})

    # ---- C3 ------------------------------------------------------------------------------------------------------
    def c3(self, doc: Document, dm: DocMeta) -> tuple[list[Chunk], list[dict]]:
        """C2 + parent-child cho quy_che: child = chunk C2 (Khoản/Điểm/bảng), parent = toàn bộ Điều. Loại khác: như C2, không parent."""
        self._last = None
        children = self.c2(doc, dm)
        parents: list[dict] = []
        if dm.doc_type == "quy_che" and self._last is not None:
            fr, secs, title = self._last
            spans: dict[str, list] = {}
            for sec in secs:
                if sec.article_key and not sec.is_preamble:
                    spans.setdefault(sec.article_key, []).append(sec)
            for key, ss in spans.items():
                a, b = self._strip(fr.ftext, min(x.start for x in ss), max(x.end for x in ss))
                mm = list(re.finditer(rf"(?m)^[ \t]*Điều\s+{ss[0].article}\b", fr.ftext[max(0, a - 300):a]))
                if mm:  # dòng tiêu đề "Điều N." đứng ngay trước nội dung của Điều
                    a = max(0, a - 300) + mm[-1].start()
                    a = self._strip(fr.ftext, a, b)[0]
                if a >= b:
                    continue
                parts = [x for x in self._crumb_parts(ss[0])[:2]]
                parts = [x for x in parts if not x.startswith("Khoản")]
                content = fr.ftext[a:b]
                embed = f"{make_breadcrumb(title, *parts)} {content}"
                cs, ce = fr.to_doc(a, b)
                s0 = ss[0]
                meta = self._meta(doc, dm, cs, ce, content, chapter=s0.chapter, article=s0.article, doc_heading=title,
                                  fallback=s0.fallback, parent_id=None)
                parents.append({"parent_id": f"{doc.doc_id}::{key}", "embed_text": embed, "content": content,
                                "n_tokens": count_tokens(embed), "metadata": meta.model_dump(mode="json")})
        ids = {p_["parent_id"] for p_ in parents}
        for c in children:
            c.config = "c3"
            if c.metadata.parent_id not in ids:
                c.metadata.parent_id = None
        return children, parents

    @staticmethod
    def _nganh_kw(u: Unit) -> dict:
        """nganh_ma / nganh_ten của chunk: từ nhãn ngành trong breadcrumb (ctdt nhiều ngành) hoặc từ mục theo trang (tờ rơi)."""
        for q in u.crumb_parts:
            if isinstance(q, ProgLabel):
                return {"nganh_ma": q.ma, "nganh_ten": q.ten, "nganh_ma_goc": q.ma_goc}
        return {"nganh_ma": u.sec.nganh_ma, "nganh_ten": u.sec.nganh_ten, "nganh_ma_goc": u.sec.nganh_ma_goc}

    def _crumb(self, title: str | None, u: Unit) -> str:
        parts = list(u.crumb_parts)
        k = max((i for i, x in enumerate(parts) if not isinstance(x, ProgLabel)), default=-1)  # phần cuối không phải nhãn ngành
        if u.merged_keys and len(u.merged_keys) > 1 and k >= 0 and parts[k]:
            last = parts[k]
            if last.startswith("Khoản"):
                nums = [x.rsplit("::k", 1)[1] for x in u.merged_keys if "::k" in x and "::" not in x.rsplit("::k", 1)[1]]
                if nums:
                    parts[k] = f"Khoản {nums[0]}-{nums[-1]}"
            elif last.startswith("Điểm"):
                ls = [x.rsplit("::", 1)[1] for x in u.merged_keys if len(x.rsplit("::", 1)[1]) == 1]
                if len(ls) > 1:
                    parts[k] = f"Điểm {ls[0]}-{ls[-1]})"
        return make_breadcrumb(title, *parts)

    def _budget_if_split(self, fr: FilterResult, parts: list, title: str | None, a: int, b: int) -> int | None:
        """Ngân sách token cho nội dung nếu phải cắt; None nếu đoạn đã vừa (cùng breadcrumb)."""
        budget = self.max_t - count_tokens(make_breadcrumb(title, *parts) + " ") - 1
        return None if count_tokens(fr.ftext[a:b]) <= budget else budget

    def _emit(self, fr: FilterResult, sec: Section, parts: list, title: str | None, a: int, b: int, units: list[Unit]) -> None:
        """Một đơn vị: nguyên khối nếu vừa, ngược lại cắt recursive (mỗi mảnh giữ breadcrumb)."""
        a, b = self._strip(fr.ftext, a, b)
        if a >= b:
            return
        budget = self._budget_if_split(fr, parts, title, a, b)
        if budget is None:
            units.append(Unit(sec, a, b, parts))
            return
        for k, (x, y) in enumerate(split_recursive(fr.ftext, a, b, budget, self.cfg["recursive_overlap_ratio"]), 1):
            units.append(Unit(sec, x, y, parts, piece=k))

    @staticmethod
    def _points(ftext: str, a: int, b: int) -> list[tuple[str | None, int, int]] | None:
        """Tách [a, b) theo Điểm a), b), c)... (liên tiếp). Trả [(chữ cái | None cho phần dẫn, start, end)]; None nếu < 2 Điểm."""
        picked, nxt = [], 0
        for p in line_starts(ftext, a, b, RE_POINT):
            letter = ftext[p:].lstrip()[0]
            if nxt < len(POINT_LETTERS) and letter == POINT_LETTERS[nxt]:
                picked.append((letter, p))
                nxt += 1
        if len(picked) < 2:
            return None
        out: list[tuple[str | None, int, int]] = []
        if ftext[a:picked[0][1]].strip():
            out.append((None, a, picked[0][1]))
        for i, (letter, p) in enumerate(picked):
            out.append((letter, p, picked[i + 1][1] if i + 1 < len(picked) else b))
        return out

    @staticmethod
    def _bullets(ftext: str, a: int, b: int, budget: int) -> list[tuple[int, int]] | None:
        """Chia phần dài theo gạch đầu dòng: gom các gạch liên tiếp tới ngưỡng budget; None nếu không có gạch đầu dòng."""
        pos = line_starts(ftext, a, b, RE_BULLET)
        if len(pos) < 2:
            return None
        cuts = ([a] if pos[0] > a else []) + pos + [b]
        groups: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = None
        for x, y in zip(cuts, cuts[1:]):
            if cur and count_tokens(ftext[cur[0]:y]) <= budget:
                cur = (cur[0], y)
            else:
                if cur:
                    groups.append(cur)
                cur = (x, y)
        groups.append(cur)
        return groups

    def _prog_parts(self, parts: list, pos: int) -> list:
        """parts + nhãn ngành của vị trí `pos` (nếu tài liệu có mục ngành và pos đã nằm trong một mục ngành)."""
        lab = program_at(self._progs, pos) if self._progs else None
        return parts + [lab] if lab else parts  # lab đã là ProgLabel (mang tên chuẩn + mã)

    def _to_units(self, fr: FilterResult, secs: list[Section], title: str | None, doc_type: str = "khac") -> list[Unit]:
        units: list[Unit] = []
        for s in secs:
            parts = self._crumb_parts(s)
            a, b = self._strip(fr.ftext, s.start, s.end)
            if a >= b:
                continue
            tabs = tables_in(fr.ftext, a, b)
            cuts = [pr.start for pr in self._progs if a < pr.start < b]  # ranh giới ngành nằm trong mục này
            if not tabs and not cuts:
                self._text_units(fr, s, self._prog_parts(parts, a), title, a, b, units)
                continue
            excl = sorted({span for t in tabs for span in t.excluded})
            pos, k = a, 0
            segs: list[tuple[int, int, Table | None]] = []
            for x, y in excl:
                if x > pos:
                    segs.append((pos, x, None))
                pos = max(pos, y)
            if pos < b:
                segs.append((pos, b, None))
            for t in tabs:
                segs.append((t.start, t.end, t))
            segs.sort(key=lambda z: z[0])
            for x, y, t in segs:
                if t is None:
                    edges = [x] + [c for c in cuts if x < c < y] + [y]  # đoạn chữ bị cắt tại ranh giới ngành
                    for x2, y2 in zip(edges, edges[1:]):
                        if fr.ftext[x2:y2].strip():
                            k += 1
                            self._text_units(fr, replace(s, key=f"{s.key}::x{k}"), self._prog_parts(parts, x2), title, x2, y2, units)
                    continue
                self._tno += 1
                if t.promoted and self._cur:
                    d_, f_, m_ = self._cur
                    self.promoted_log.setdefault((d_.doc_id, t.start), {"doc_id": d_.doc_id, "trang": d_.pages_for(*f_.to_doc(t.start, t.end))[0],
                                                                       "tieu_de": t.title, "in_scope": m_.in_scope})
                tparts = self._prog_parts(parts, t.start)
                same = t.title and any(q and (t.title.lower() in q.lower() or q.lower() in t.title.lower())
                                        for q in ([parts[-1]] if parts else []) + [x for x in tparts if isinstance(x, ProgLabel)])
                crumb = make_breadcrumb(title, *tparts, None if same else short_table_title(t.title))  # tiêu đề bảng trùng mục hiện tại thì không lặp lại
                for tc in chunk_table(t, self._tno, fr.ftext, doc_type, crumb, self.max_t, self.cfg["table_small_max_tokens"],
                                      self.cfg["note_inline_max_tokens"]):
                    units.append(Unit(s, tc.start, tc.end, tparts, tc=tc, table_title=t.title, table_crumb=crumb))
        return units

    def _text_units(self, fr: FilterResult, s: Section, parts: list, title: str | None, a: int, b: int, units: list[Unit]) -> None:
        a, b = self._strip(fr.ftext, a, b)
        if a >= b:
            return
        budget = self._budget_if_split(fr, parts, title, a, b)
        if budget is None:
            units.append(Unit(s, a, b, parts))
            return
        subs = self._points(fr.ftext, a, b) if s.kind in ("clause", "article", "lead") else None
        if subs:  # Khoản/Điều dài: tách theo Điểm; chỉ recursive khi một Điểm vẫn quá dài
            for letter, x, y in subs:
                sub = replace(s, key=f"{s.key}::{letter or 'lead'}", parent_key=s.key, point=letter)
                self._emit(fr, sub, self._crumb_parts(sub) + [q for q in parts if isinstance(q, ProgLabel)], title, x, y, units)
            return
        groups = self._bullets(fr.ftext, a, b, budget) if s.kind in ("text", "section") else None
        if groups:
            for x, y in groups:
                self._emit(fr, s, parts, title, x, y, units)
            return
        self._emit(fr, s, parts, title, a, b, units)

    @staticmethod
    def _strip(text: str, s: int, e: int) -> tuple[int, int]:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        return s, e

    def _merge_small(self, fr: FilterResult, units: list[Unit], title: str | None) -> list[Unit]:
        """Gộp chunk < min_tokens với chunk liền kề CÙNG parent_key (không gộp qua 2 Điều, không gộp mảnh recursive)."""
        out: list[Unit] = []
        for i, u in enumerate(units):
            small = u.piece is None and u.tc is None and count_tokens(fr.ftext[u.start:u.end]) < self.min_t and not u.sec.is_preamble
            if small and i + 1 < len(units) and self._can_merge(fr, u, units[i + 1], title):
                units[i + 1] = self._join(u, units[i + 1])
            elif small and out and self._can_merge(fr, out[-1], u, title):
                out[-1] = self._join(out[-1], u)
            else:
                out.append(u)
        return out

    def _can_merge(self, fr: FilterResult, a: Unit, b: Unit, title: str | None) -> bool:
        if a.tc or b.tc or a.piece or b.piece or a.sec.parent_key != b.sec.parent_key or a.sec.is_preamble or b.sec.is_preamble:
            return False
        if [q for q in a.crumb_parts if isinstance(q, ProgLabel)] != [q for q in b.crumb_parts if isinstance(q, ProgLabel)]:
            return False  # không gộp chunk của hai ngành khác nhau
        j = self._join(a, b)
        return count_tokens(f"{self._crumb(title, j)} {fr.ftext[j.start:j.end]}") <= self.max_t

    @staticmethod
    def _join(a: Unit, b: Unit) -> Unit:
        keys = (a.merged_keys or [a.sec.key]) + (b.merged_keys or [b.sec.key])
        return Unit(a.sec, a.start, b.end, list(a.crumb_parts), None, keys)

    @staticmethod
    def _unique(chunks: list[Chunk]) -> list[Chunk]:
        seen: dict[str, int] = {}
        for c in chunks:
            n = seen.get(c.chunk_id, 0)
            seen[c.chunk_id] = n + 1
            if n:
                c.chunk_id = f"{c.chunk_id}~{n}"
        return chunks


def write_drop_report(path: Path, rows: list[tuple[Document, DocMeta, FilterResult]]) -> list[dict]:
    """procedural_drop_report.csv: ký tự bị bỏ theo nhãn và tỉ lệ %. Trả danh sách dòng (đã sắp theo % giảm dần)."""
    recs = []
    for doc, dm, fr in rows:
        by = fr.removed_chars()
        total = len(doc.text)
        removed = sum(by.values())
        recs.append({"doc_id": doc.doc_id, "doc_type": dm.doc_type, "total_chars": total,
                     **{k: by.get(k, 0) for k in DROP_LABELS}, "removed_total": removed,
                     "pct_removed": round(100 * removed / total, 2) if total else 0.0, "warnings": " | ".join(fr.warnings)})
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0]) if recs else ["doc_id"])
        w.writeheader()
        w.writerows(recs)
    return sorted(recs, key=lambda r: -r["pct_removed"])


def write_nganh_report(d: Path, rows: list[dict]) -> None:
    """nganh_matching.csv: tên gốc -> tên chuẩn, mã, cách ghép, điểm (để người duyệt); nganh_unmatched.md: các tên CHƯA ghép được."""
    rows = sorted(rows, key=lambda r: (r["cach_ghep"] in ("chua_ghep", "ma_chua_co"), r["doc_id"], r["ten_goc"]))
    with (d / "nganh_matching.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["doc_id", "ten_goc", "ma_goc", "ten_chuan", "ma", "cach_ghep", "diem"])
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if r["cach_ghep"] in ("chua_ghep", "ma_chua_co")]
    md = ["# Tên ngành chưa ghép được vào configs/nganh.yaml", "",
          "Giữ nguyên tên gốc trong breadcrumb. Không tự thêm alias nào dưới ngưỡng 0.85; thêm vào danh mục (hoặc alias) sau khi duyệt.", ""]
    md += [f"- {r['doc_id'][:20]}… | tên: {r['ten_goc']} | mã: {r['ma_goc'] or '(không có)'} | {r['cach_ghep']} | điểm {r['diem']}" for r in bad] or ["(không có)"]
    (d / "nganh_unmatched.md").write_text(chr(10).join(md) + chr(10), encoding="utf-8")


def chunk_corpus(config: str = "all", only: set[str] | None = None, out_dir: Path | None = None,
                 clean_dir: Path | None = None, doc_meta_path: Path | None = None) -> dict:
    """Chạy chunking cho c1|c2|c3|all, ghi JSONL, docs/*.txt, procedural_drop_report.csv, chunking.log vào out_dir."""
    cfg = chunking_config()
    paths = cfg["paths"]
    out_dir = out_dir or paths["out_dir"]
    clean_dir = clean_dir or paths["clean_dir"]
    doc_meta_path = doc_meta_path or paths["doc_meta"]
    if not doc_meta_path.exists():
        raise SystemExit(f"Chưa có {doc_meta_path}: duyệt configs/doc_meta.draft.yaml và đổi tên thành doc_meta.yaml trước.")
    (out_dir / "chunks").mkdir(parents=True, exist_ok=True)
    (out_dir / "docs").mkdir(parents=True, exist_ok=True)
    fh_log = logging.FileHandler(out_dir / "chunks" / "chunking.log", mode="w", encoding="utf-8")
    fh_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh_log)
    log.setLevel(logging.INFO)
    handlers: dict[str, object] = {}
    try:
        metas = load_doc_metas(doc_meta_path, paths["manifest"])
        chunker = Chunker(cfg, metas, load_aliases(paths["aliases"]))
        names = ["c1", "c2", "c3"] if config == "all" else [config]
        log.info("bắt đầu: config=%s, %d tài liệu trong doc_meta", names, len(metas))
        handlers = {n: open(out_dir / "chunks" / f"{n}_chunks.jsonl", "w", encoding="utf-8") for n in names}
        if "c3" in names:
            handlers["c3_parents"] = open(out_dir / "chunks" / "c3_parents.jsonl", "w", encoding="utf-8")
        handlers["excluded"] = open(out_dir / "chunks" / "excluded_chunks.jsonl", "w", encoding="utf-8")
        counts = {n: 0 for n in names}
        skipped: list[dict] = []
        vlm_dir = paths.get("table_vlm_dir") if cfg.get("use_table_vlm") else None
        log.info("use_table_vlm=%s", bool(vlm_dir))
        ablation = bool(vlm_dir) and "c2" in names  # c2_novlm_chunks.jsonl: c2 với văn bản gốc, chỉ cho tài liệu có trang trong table_vlm/
        if ablation:
            handlers["c2_novlm"] = open(out_dir / "chunks" / "c2_novlm_chunks.jsonl", "w", encoding="utf-8")
        for doc in iter_documents(clean_dir, only, vlm_dir, with_plain=ablation, fixes_path=paths.get("table_vlm_fixes")):
            dm = metas.get(doc.doc_id)
            if dm is None:
                log.warning("%s: không có trong doc_meta, bỏ qua", doc.doc_id)
                continue
            if dm.trung_voi:
                log.info("%s: bản trùng của %s -> bỏ qua, không chunk", doc.doc_id, dm.trung_voi)
                skipped.append({"doc_id": doc.doc_id, "ly_do": f"trung_voi={dm.trung_voi}"})
                continue
            (out_dir / "docs" / f"{doc.doc_id}.txt").write_text(doc.text, encoding="utf-8")
            pages = [{"start": s.start, "end": s.end, "page": s.page, "route": s.route} for s in doc.spans]
            (out_dir / "docs" / f"{doc.doc_id}.pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
            for name in names:
                if name == "c3":
                    chunks, parents = chunker.c3(doc, dm)
                    for pr in parents if dm.in_scope else []:  # tài liệu ngoài phạm vi: không có parent trong file đầu vào embedding
                        handlers["c3_parents"].write(json.dumps(pr, ensure_ascii=False) + "\n")
                else:
                    chunks = chunker.c1(doc, dm) if name == "c1" else chunker.c2(doc, dm)
                # in_scope=false: vẫn chunk nhưng ghi riêng, KHÔNG vào c*_chunks.jsonl (đầu vào bước embedding)
                target = handlers[name] if dm.in_scope else handlers["excluded"]
                for c in chunks:
                    target.write(c.model_dump_json() + "\n")
                key = name if dm.in_scope else f"excluded_{name}"
                counts[key] = counts.get(key, 0) + len(chunks)
                if name == "c2" and ablation and dm.in_scope and getattr(doc, "plain", None) is not None:
                    base = chunker.c2(doc.plain, dm)
                    for c in base:
                        handlers["c2_novlm"].write(c.model_dump_json() + chr(10))
                    counts["c2_novlm"] = counts.get("c2_novlm", 0) + len(base)
        if chunker.drop_rows:
            top = write_drop_report(out_dir / "chunks" / "procedural_drop_report.csv", chunker.drop_rows)
            for r in top[:10]:
                log.info("tỉ lệ bỏ cao: %s %s %.2f%% (%d/%d ký tự)", r["doc_id"], r["doc_type"], r["pct_removed"], r["removed_total"], r["total_chars"])
        if chunker.promoted_log:
            with (out_dir / "chunks" / "table_title_promoted.csv").open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["doc_id", "trang", "tieu_de", "in_scope"])
                w.writeheader()
                w.writerows(chunker.promoted_log.values())
        if chunker.nganh_log:
            write_nganh_report(out_dir / "chunks", list(chunker.nganh_log.values()))
        for h in handlers.values():
            h.flush()
        log.info("xong: %s", counts)
        if config in ("all", "c1", "c2", "c3"):
            from .stats import write_stats
            write_stats(out_dir, names, skipped, [m for m in metas if m not in {x["doc_id"] for x in skipped}])
        return counts
    finally:
        for h in handlers.values():
            h.close()
        log.removeHandler(fh_log)
        fh_log.close()

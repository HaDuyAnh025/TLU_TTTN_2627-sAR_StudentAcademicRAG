"""Đọc data/interim/clean/*.json (CHỈ ĐỌC), nối trang thành văn bản tài liệu và ánh xạ ký tự → trang."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import normalize_text

PAGE_JOIN = "\n\n"


@dataclass(frozen=True)
class PageSpan:
    """Khoảng ký tự [start, end) của một trang trong văn bản tài liệu. page: số trang từ 1, None nếu là ảnh đơn."""

    start: int
    end: int
    page: int | None
    route: str
    source: str


@dataclass
class Document:
    """Một tài liệu đã nối trang. doc_id = tên file bỏ đuôi."""

    doc_id: str
    file: str
    text: str
    spans: list[PageSpan] = field(default_factory=list)
    _ocr_blocks: list[tuple[int, int]] | None = field(default=None, repr=False)

    def pages_for(self, start: int, end: int) -> tuple[int | None, int | None]:
        """(page_start, page_end) của khoảng ký tự [start, end); (None, None) với ảnh đơn."""
        pages = [s.page for s in self._overlap(start, end) if s.page is not None]
        return (min(pages), max(pages)) if pages else (None, None)

    def routes_for(self, start: int, end: int) -> list[str]:
        """Danh sách route (đã khử trùng, giữ thứ tự) của các trang chunk đi qua."""
        return list(dict.fromkeys(s.route for s in self._overlap(start, end)))

    def sources_for(self, start: int, end: int) -> list[str]:
        """Danh sách nguon_van_ban của các trang chunk đi qua."""
        return list(dict.fromkeys(s.source for s in self._overlap(start, end)))

    def ocr_table_suspect(self, start: int, end: int, min_lines: int = 4) -> bool:
        """Khoảng [start, end) có chồng lên khối >= min_lines dòng liên tiếp chứa "|" nằm TRONG trang OCR (theo vị trí ký tự)."""
        if self._ocr_blocks is None:
            blocks, pos, run = [], 0, []
            for line in self.text.split("\n") + [""]:
                if "|" in line:
                    run.append((pos, pos + len(line)))
                else:
                    if len(run) >= min_lines and any(sp.route == "ocr" and sp.start <= run[0][0] < sp.end for sp in self.spans):
                        blocks.append((run[0][0], run[-1][1]))
                    run = []
                pos += len(line) + 1
            self._ocr_blocks = blocks
        return any(a < max(end, start + 1) and b > start for a, b in self._ocr_blocks)

    def _overlap(self, start: int, end: int) -> list[PageSpan]:
        e = max(end, start + 1)
        return [s for s in self.spans if s.start < e and s.end > start]


def doc_id_of(file: str) -> str:
    """doc_id = tên file bỏ đuôi."""
    return Path(file).stem


_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _norm_row(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _trailing_header(text: str) -> tuple[str, bool] | None:
    """Nếu văn bản kết thúc bằng bảng Markdown: (dòng header chuẩn hóa | None nếu bảng không có header trong trang này, True)."""
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines or not lines[-1].lstrip().startswith("|"):
        return None
    i = len(lines) - 1
    while i > 0 and lines[i - 1].lstrip().startswith("|"):
        i -= 1
    run = lines[i:]
    if len(run) >= 2 and _SEP.match(run[1]):
        return _norm_row(run[0]), True
    return "", False


def build_document(data: dict) -> Document:
    """Dựng Document từ nội dung JSON của clean/. Trang xếp theo `page` (None = ảnh đơn, coi là 1 trang).

    Bảng Markdown vắt qua 2 trang: nếu trang sau lặp lại dòng header (và dòng `|---|`) của bảng trang trước thì bỏ phần lặp,
    và nối bằng một dấu xuống dòng (không chèn dòng trống) để bảng liền mạch.
    """
    pages = sorted(data["pages"], key=lambda p: (p["page"] is None, p["page"] or 0))
    parts: list[str] = []
    spans: list[PageSpan] = []
    pos = 0
    carry: str | None = None  # header của bảng đang mở ở cuối trang trước
    for p in pages:
        t = normalize_text(p["text"])
        if not t:
            continue
        join = PAGE_JOIN
        if parts and carry is not None and t.lstrip().startswith("|"):
            lines = t.split("\n")
            if _norm_row(lines[0]) == carry and len(lines) > 1 and _SEP.match(lines[1]):
                lines = lines[2:]  # header lặp lại -> bỏ
                join = "\n"
            elif len(lines) > 1 and _SEP.match(lines[1]):
                join = PAGE_JOIN  # bảng mới có header khác
            else:
                join = "\n"  # dòng dữ liệu tiếp nối
            t = "\n".join(lines).strip()
            if not t:
                continue
        if parts:
            pos += len(join)
        spans.append(PageSpan(pos, pos + len(t), None if p["page"] is None else p["page"] + 1, p["route"], p["nguon_van_ban"]))
        parts.append(join + t if parts else t)
        pos += len(t)
        tr = _trailing_header(t)
        if tr is None:
            carry = None
        elif tr[1]:
            carry = tr[0]
        # bảng tiếp nối không có header trong trang này: giữ carry cũ
    return Document(doc_id_of(data["file"]), data["file"], "".join(parts), spans)


def load_table_vlm_fixes(path: Path | None) -> dict[str, dict]:
    """configs/table_vlm_fixes.yaml -> {doc_id: {"fixes": [...], "force": {page 0-based}}}, chỉ các mục trang_thai = da_xac_nhan."""
    if path is None or not path.exists():
        return {}
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict] = {}
    new = lambda: {"fixes": [], "force": set(), "reject": set()}  # noqa: E731
    last: dict[tuple, dict] = {}  # cùng (doc_id, trang, find): mục SAU CÙNG thắng (mục sau là bản sửa lại của mục trước), không áp dụng chồng
    for fx in raw.get("fixes") or []:
        if fx.get("trang_thai") == "da_xac_nhan":
            last[(fx["doc_id"], fx["page_1based"], fx["find"])] = fx
    for fx in last.values():
        out.setdefault(fx["doc_id"], new())["fixes"].append(fx)
    for key, field in (("force_accept", "force"), ("force_reject", "reject")):
        for fa in raw.get(key) or []:
            if fa.get("trang_thai") == "da_xac_nhan":
                out.setdefault(fa["doc_id"], new())[field].add(fa["page_1based"] - 1)
    return out


def apply_table_vlm(data: dict, vlm: dict | None, fixes: dict | None = None) -> dict:
    """Thay các trang của clean/ bằng trang tương ứng trong lớp table_vlm/ (cùng chỉ số `page`), bỏ trang need_review.

    `fixes` ({"fixes", "force"} của tài liệu, xem load_table_vlm_fixes): áp dụng sửa tay (find phải khớp đúng 1 lần, không thì ValueError)
    và cho phép dùng lại trang need_review nằm trong `force`; trang nằm trong `reject` bị loại (quay về văn bản OCR của clean/). Không sửa `data` đầu vào. Trang thay thế mang route/nguon_van_ban `vlm_table`.
    """
    if not vlm:
        return data
    fixes = {"fixes": [], "force": set(), "reject": set(), **(fixes or {})}
    pages_vlm = {p["page"]: dict(p) for p in vlm.get("pages", [])}
    did = doc_id_of(data["file"])
    for fx in fixes["fixes"]:
        pg = pages_vlm.get(fx["page_1based"] - 1)
        if pg is None:
            raise ValueError(f"table_vlm_fixes: {did} trang {fx['page_1based']} không có trong table_vlm/")
        n = pg["text"].count(fx["find"])
        if n != 1:
            raise ValueError(f"table_vlm_fixes: {did} trang {fx['page_1based']}: chuỗi find khớp {n} lần (cần đúng 1): {fx['find']!r}")
        pg["text"] = pg["text"].replace(fx["find"], fx["replace"])
    good = {k: p for k, p in pages_vlm.items() if (not p.get("need_review") or k in fixes["force"]) and k not in fixes["reject"] and p.get("text", "").strip()}
    if not good:
        return data
    pages = [({**p, "route": "vlm_table", "nguon_van_ban": "vlm_table", "text": good[p["page"]]["text"]} if p["page"] in good else p)
             for p in data["pages"]]
    return {**data, "pages": pages}


def iter_documents(clean_dir: Path, only: set[str] | None = None, table_vlm_dir: Path | None = None, with_plain: bool = False,
                   fixes_path: Path | None = None):
    """Duyệt các tài liệu trong clean/ theo thứ tự tên file; bỏ `_manifest.json` (và không đọc `*.sha256`).

    `table_vlm_dir` (khi use_table_vlm = true): dùng trang đọc lại bằng VLM thay cho trang tương ứng, trừ trang need_review.
    """
    fixes = load_table_vlm_fixes(fixes_path) if table_vlm_dir is not None else {}
    for p in sorted(clean_dir.glob("*.json")):
        if p.name == "_manifest.json":
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        did = doc_id_of(data["file"])
        if only and did not in only and p.stem not in only:  # doc_id lấy từ trường `file` (tên file trên đĩa có thể khác)
            continue
        plain = None
        if table_vlm_dir is not None and (table_vlm_dir / f"{did}.json").exists():
            if with_plain:  # bản không dùng VLM của cùng tài liệu (cho thí nghiệm ablation)
                plain = build_document(data)
            data = apply_table_vlm(data, json.loads((table_vlm_dir / f"{did}.json").read_text(encoding="utf-8")), fixes.get(did))
        doc = build_document(data)
        doc.plain = plain  # type: ignore[attr-defined]
        yield doc

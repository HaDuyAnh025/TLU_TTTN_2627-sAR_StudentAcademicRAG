"""Nhận diện mục theo NGÀNH trong tài liệu ctdt nhiều ngành, để đưa "Ngành <tên> (<mã>)" vào breadcrumb mọi chunk thuộc mục đó.

Các dạng tiêu đề nhận được (tọa độ theo văn bản đã lọc `ftext`):
  - "KHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH THANH NHẠC" (viết hoa; không có mã thì chỉ có tên)
  - "NGÀNH QUẢN TRỊ KINH DOANH ĐỊNH HƯỚNG ỨNG DỤNG" (viết hoa) + "Tên ngành đào tạo: ..." / "Mã ngành đào tạo: 8340101" ngay sau đó
  - "Tên ngành đào tạo: ..." đứng riêng
  - "Ngành Quản trị kinh doanh (8340101)" trên một dòng
  - mục đánh số chứa tên ngành: "1. Ngành Kế toán", "II. Ngành Luật"
Một mục ngành kéo dài từ tiêu đề của nó tới tiêu đề ngành kế tiếp (hoặc hết tài liệu).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml

R_KHUNG = re.compile(r"^\s*(?:KHUNG\s+)?CHƯƠNG\s+TRÌNH\s+ĐÀO\s+TẠO\s+NGÀNH\s+(?P<name>\S.*?)\s*$")
R_CAPS = re.compile(r"^\s*NGÀNH\s+(?P<name>\S.*?)\s*$")
R_TEN = re.compile(r"^\s*(?:\d+[.)]\s*)?Tên\s+ngành(?:\s+đào\s+tạo)?\s*:\s*(?P<name>\S.*?)\s*$", re.I)
R_MA = re.compile(r"^\s*(?:\d+[.)]\s*)?Mã\s+ngành(?:\s+đào\s+tạo)?\s*:\s*(?P<code>\d[\d ]{4,9}[A-Z]?)\s*$", re.I)
R_ONE = re.compile(r"^\s*(?:(?:[IVX]+|\d+)[.)]\s+)?Ngành\s+(?P<name>[^|()]{2,80}?)\s*\((?P<code>\d{7}[A-Z]?)\)\s*$")
R_NUM = re.compile(r"^\s*(?:[IVX]+|\d+)[.)]\s+Ngành\s+(?P<name>[^|()]{2,70}?)\s*$")
R_ORIENT = re.compile(r"\s*[–—\-?]?\s*(?P<o>ĐỊNH\s+HƯỚNG\s+.+)$", re.I)
MAX_WORDS = 14


class ProgLabel(str):
    """Phần breadcrumb chỉ ngành (để phân biệt với Chương/Điều/Khoản/tiêu đề bảng); mang theo tên chuẩn và mã cho metadata chunk."""

    ten: str | None = None
    ma: str | None = None
    ma_goc: str | None = None

    def __new__(cls, label: str, ten: str | None = None, ma: str | None = None, ma_goc: str | None = None):
        o = super().__new__(cls, label)
        o.ten, o.ma, o.ma_goc = ten, ma, ma_goc
        return o


FUZZY_MIN = 0.85  # ngưỡng ghép tên (không có mã) với danh mục


def norm_name(s: str) -> str:
    """Tên ngành chuẩn hóa để so khớp: bỏ dấu, chữ thường, "&" -> "va", bỏ ký tự không phải chữ/số, bỏ tiền tố "ngành"."""
    s = s.replace("đ", "d").replace("Đ", "D").replace("&", " va ")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return re.sub(r"^nganh ", "", s)


@dataclass(frozen=True)
class Match:
    ten: str  # tên dùng trong breadcrumb (chuẩn nếu ghép được)
    ma: str | None
    cach: str  # ma | ten_chuan_hoa | alias | fuzzy | chua_ghep | ma_chua_co
    diem: float
    ten_goc: str
    ma_goc: str | None  # mã trích được từ tài liệu (không phải mã ngành gốc)
    nganh_goc: str | None = None  # mã ngành gốc của chương trình riêng (ma_nganh_goc trong nganh.yaml)


class Catalog:
    """configs/nganh.yaml: danh mục ngành chuẩn. Ghép theo MÃ trước; không có mã thì so tên chuẩn hóa với ten + aliases (difflib >= 0.85)."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.by_ma = {re.sub(r"\s+", "", e["ma"]): e for e in entries}

    @classmethod
    def load(cls, path: Path | None) -> "Catalog":
        if path is None or not Path(path).exists():
            return cls([])
        return cls((yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("nganh") or [])

    def resolve(self, name: str, code: str | None, bac: str | None = None) -> Match:
        code = re.sub(r"\s+", "", code) if code else None
        if code:
            e = self.by_ma.get(code)
            if e:
                return Match(e["ten"], e["ma"], "ma", 1.0, name, code, e.get("ma_nganh_goc"))
            return Match(name, code, "ma_chua_co", 0.0, name, code)  # có mã nhưng chưa có trong danh mục: giữ nguyên
        n = norm_name(name)
        best: tuple[float, dict | None, str] = (0.0, None, "")
        for e in self.entries:
            if bac and e.get("bac_dao_tao") and e["bac_dao_tao"] != bac:
                continue  # cùng tên ở bậc khác (7340101 và 8340101) không lẫn nhau
            for cand, kind in [(e["ten"], "ten")] + [(a, "alias") for a in e.get("aliases") or []]:
                c = norm_name(cand)
                sc = 1.0 if c == n else SequenceMatcher(None, n, c).ratio()
                if sc > best[0] or (sc == best[0] == 1.0 and kind == "ten"):
                    best = (sc, e, ("ten_chuan_hoa" if kind == "ten" else "alias") if sc == 1.0 else "fuzzy")
        if best[1] is not None and best[0] >= FUZZY_MIN:
            return Match(best[1]["ten"], best[1]["ma"], best[2], round(best[0], 3), name, None, best[1].get("ma_nganh_goc"))
        return Match(name, None, "chua_ghep", round(best[0], 3), name, None)


@dataclass(frozen=True)
class Program:
    start: int  # vị trí đầu dòng tiêu đề ngành trong ftext
    label: str  # "Ngành <tên chuẩn> (<mã>)"
    ten: str | None = None  # tên chuẩn (hoặc tên gốc nếu chưa ghép)
    ma: str | None = None
    match: Match | None = None

    @property
    def ma_goc(self) -> str | None:
        return self.match.nganh_goc if self.match else None


PROPER = {"ngôn ngữ anh": "Ngôn ngữ Anh", "ngôn ngữ trung quốc": "Ngôn ngữ Trung Quốc", "ngôn ngữ nhật": "Ngôn ngữ Nhật",
          "ngôn ngữ hàn quốc": "Ngôn ngữ Hàn Quốc", "việt nam học": "Việt Nam học"}  # tên riêng bị hạ chữ thường khi đổi từ chữ in hoa


def _name(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw.replace("?", "–")).strip(" .:–-")
    s = re.sub(r"^ngành\s+", "", s, flags=re.I)  # "Ngành ngành X" -> "X"
    s = re.sub(r"\s*–\s*", " – ", s)
    if s.isupper():
        s = s[:1] + s[1:].lower()
        s = PROPER.get(s.lower(), s)
    return s


def _label(name: str, code: str | None, orient: str | None = None) -> str:
    out = f"Ngành {name}" + (f" – {orient.lower()}" if orient else "")
    return out + (f" ({re.sub(r'  +', ' ', code).strip()})" if code else "")


def _mk(catalog: "Catalog | None", bac: str | None, name: str, code: str | None, orient: str | None = None) -> tuple[str, Match | None]:
    """(nhãn breadcrumb, kết quả ghép). Không có danh mục thì nhãn dựng từ tên/mã gốc."""
    if catalog is None or not catalog.entries:
        return _label(name, code, orient), None
    m = catalog.resolve(name, code, bac)
    return _label(m.ten, m.ma if m.cach != "chua_ghep" else code, orient), m


def _base(label: str) -> str:
    """Tên ngành (không mã, không định hướng) để so sánh hai nhãn có cùng ngành không."""
    return re.split(r" [(–]", label)[0].lower().replace("-", "–").strip()


def find_programs(ftext: str, catalog: "Catalog | None" = None, bac: str | None = None) -> list[Program]:
    """Danh sách mục ngành theo vị trí tăng dần; rỗng nếu văn bản không có cấu trúc nhiều ngành."""
    lines = ftext.split("\n")
    offs, p = [], 0
    for l in lines:
        offs.append(p)
        p += len(l) + 1
    out: list[Program] = []
    last_i = -99

    def code_after(i: int, span: int) -> str | None:
        for j in range(i + 1, min(len(lines), i + 1 + span)):
            m = R_MA.match(lines[j])
            if m:
                return m.group("code")
        return None

    def name_after(i: int, span: int) -> str | None:
        for j in range(i + 1, min(len(lines), i + 1 + span)):
            m = R_TEN.match(lines[j])
            if m:
                return m.group("name")
        return None

    for i, l in enumerate(lines):
        s = l.strip()
        if not s or s.startswith("|") or len(s.split()) > MAX_WORDS + 8:
            continue
        lab, mt = None, None
        m = R_KHUNG.match(l)
        if m and s.upper() == s and len(m.group("name").split()) <= MAX_WORDS:
            lab, mt = _mk(catalog, bac, _name(m.group("name")), code_after(i, 12))
        elif (m := R_CAPS.match(l)) and s.upper() == s and len(m.group("name").split()) <= MAX_WORDS:
            head = m.group("name")
            o = R_ORIENT.search(head)
            base = head[:o.start()] if o else head
            ten = name_after(i, 15)
            lab, mt = _mk(catalog, bac, _name(ten or base), code_after(i, 15), _name(o.group("o")) if o else None)
        elif (m := R_TEN.match(l)) and i - last_i > 8:
            lab, mt = _mk(catalog, bac, _name(m.group("name")), code_after(i, 3))
        elif m := R_ONE.match(l):
            lab, mt = _mk(catalog, bac, _name(m.group("name")), m.group("code"))
        elif (m := R_NUM.match(l)) and not s.endswith((".", ";", ",", ":")) and len(s.split()) <= MAX_WORDS:
            lab, mt = _mk(catalog, bac, _name(m.group("name")), code_after(i, 6))
        if lab:
            if not (out and _base(out[-1].label) == _base(lab)):  # cùng ngành nhắc lại (kể cả không kèm mã) thì không mở mục mới
                out.append(Program(offs[i], lab, mt.ten if mt else _name_of(lab), mt.ma if mt else _code_of(lab), mt))
            last_i = i
    return out


def _name_of(label: str) -> str:
    return re.sub(r" \([^)]*\)$", "", re.sub(r"^Ngành ", "", label))


def _code_of(label: str) -> str | None:
    m = re.search(r"\(([^)]*)\)$", label)
    return m.group(1) if m else None


def program_at(programs: list[Program], pos: int) -> ProgLabel | None:
    """Nhãn ngành của vị trí `pos` (mục ngành gần nhất bắt đầu tại hoặc trước `pos`); None nếu đứng trước mục ngành đầu tiên."""
    cur = None
    for pr in programs:
        if pr.start <= pos:
            cur = pr
        else:
            break
    return ProgLabel(cur.label, cur.ten, cur.ma, cur.ma_goc) if cur else None

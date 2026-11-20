"""Nhận diện và lọc phần thủ tục của văn bản hành chính (dùng cho C2/C3; C1 giữ nguyên văn bản).

Bỏ: quốc hiệu/tiêu ngữ, đơn vị ban hành, "Số: ...", "Hà Nội, ngày ...", "Nơi nhận" + khối chữ ký,
dòng chỉ gồm số rời rạc. Tiêu đề văn bản -> `doc_heading`. Khối "Căn cứ ..." -> preamble.
Việc lọc làm trên bản sao; văn bản gốc (đã nối trang) không đổi và mọi vị trí vẫn quy về tọa độ gốc.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PARTS = re.compile(r"\s*\|\s*")
BOILER = [
    re.compile(p, re.I)
    for p in (
        r"^c[ộo]ng (?:h[òo]a|hoà|hoá) x[ãa] h[ộo]i ch[ủu] ngh[ĩi]a vi[ệe]t nam$",
        r"^độc lập\s*[-–—]\s*tự do\s*[-–—]\s*hạnh phúc$",
        r"^số\s*:.*$",
        r"^(hà nội|hn)\s*,?\s*ngày.*$",
        r"^(bộ giáo dục và đào tạo|trường đại học thăng long|trưởng đại học thăng long|hội đồng quản trị)$",
        r"^(phòng|trung tâm|khoa|ban|viện)\s+[^.:;]{2,60}$",
        r"^[\d\s./-]+$",
    )
]
KIND = re.compile(
    r"^(quyết định|thông báo|kế hoạch|quy chế|quy định|quy trình|hướng dẫn|bản mô tả|danh sách|danh mục|thời khóa biểu|"
    r"thời khoá biểu|lịch|chương trình|đề cương|báo cáo|biên bản|công văn|tờ trình|nội quy|thể lệ)\b", re.I)
STOP = re.compile(r"^(căn cứ|kính gửi|điều\s+\d|theo\s|nhằm\s|thực hiện\s|xét\s|chương\s+[ivxlc]+|[a-zđ]\.$|[ivx]+\.|\d+\.|\|)", re.I)
DATE_RE = re.compile(r"ng[àa]y\s+(\d{1,2})\s+th[áa]ng\s+(\d{1,2})\s+n[ăa]m\s+(\d{4})", re.I)
CAN_CU = re.compile(r"^\s*(căn cứ|theo đề nghị|xét đề nghị|xét\b.*đề nghị)", re.I)
DECIDE = re.compile(r"^\s*(quyết định|quyết nghị)\s*:\s*$", re.I)
JUNK_NUM = re.compile(r"^\s*\d{1,10}\s*$")
NOI_NHAN = re.compile(r"^\s*nơi nhận\s*(:?\s*(\|.*)?|:\s*\S.{0,60})$", re.I)
# Dòng cho thấy khối "Nơi nhận + chữ ký" đã kết thúc (bắt đầu phụ lục/văn bản đính kèm).
ATTACH = re.compile(
    r"^\s*(điều\s+\d+|chương\b|phụ lục|quy chế|quy định|hướng dẫn|\(?ban hành kèm|bản mô tả|danh mục|chương trình|"
    r"kế hoạch|điều lệ|nội quy|đề cương|\|)", re.I)
FOOTER_MAX_CHARS = 600  # khối chữ ký dài hơn ngưỡng này (hoặc > 15 dòng) coi là nghi ngờ: giữ nguyên
FOOTER_MAX_LINES = 15
SIGN = re.compile(r"^\s*(kt\.|tl\.|tm\.|q\.)?\s*(phó )?(hiệu trưởng|chủ tịch|trưởng phòng|giám đốc|trưởng khoa)\b", re.I)


QUOC_HIEU = re.compile(r"c[ộo]ng (?:h[òo]a|hoà|hoá) x[ãa] h[ộo]i|độc lập\s*[-–—]\s*tự do", re.I)


def is_strict_boiler(line: str) -> bool:
    """Khung chắc chắn là thủ tục ở BẤT KỲ vị trí nào (quốc hiệu, tiêu ngữ, Số:, Hà Nội ngày..., tên bộ/trường đứng riêng)."""
    s = line.strip()
    if not s or s.startswith("|") and s.count("|") < 2:
        return False
    if len(s) < 140 and QUOC_HIEU.search(s):
        return True
    parts = [x for x in _PARTS.split(s) if x]
    return bool(parts) and all(any(b.match(x.strip()) for b in BOILER[:5]) for x in parts)


def is_boiler_line(line: str) -> bool:
    """Dòng thuộc khung hành chính cố định (kể cả dòng OCR 2 cột ghép bằng `|`)."""
    s = line.strip()
    if not s or re.fullmatch(r"[|\s:-]+", s) and "|" in s and "---" in s:  # dòng phân cách bảng Markdown
        return False
    parts = [p for p in _PARTS.split(s) if p]
    if len(parts) >= 2 and all(re.fullmatch(r"[\d\s./-]+", p.strip()) for p in parts):
        return False  # nhiều ô toàn số ("| 20.700.000 | 22.800.000 |") là dòng bảng, không phải khung hành chính
    return all(any(b.match(p.strip()) for b in BOILER) for p in parts)


def find_heading(lines: list[str], max_lines: int = 25) -> tuple[str | None, set[int]]:
    """Tiêu đề văn bản trong ~max_lines dòng đầu (bỏ khung hành chính) và tập chỉ số dòng cấu thành nó.

    Bắt đầu ở dòng đầu tiên khớp loại văn bản (KIND); nối thêm tối đa 2 dòng phụ (dòng kế tiếp, và các dòng
    bắt đầu bằng chữ thường hoặc "V/v", "Về"); dừng ở Căn cứ/Kính gửi/Điều/bảng/mục/ngày.
    """
    cand = [(i, l.strip()) for i, l in enumerate(lines[:max_lines]) if l.strip() and not is_boiler_line(l)]
    for pos, (i, l) in enumerate(cand):
        if KIND.match(l) and not l.endswith((";", ":")) and len(l) < 200 and not CAN_CU.match(l):
            parts, idx = [l], {i}
            for j, nxt in cand[pos + 1 : pos + 5]:
                if STOP.match(nxt) or len(parts) >= 3 or DATE_RE.search(nxt):
                    break
                if (len(parts) == 1 and not nxt.endswith((".", ";", ":"))) or nxt[:1].islower() or re.match(r"^(v/v|về)\b", nxt, re.I):
                    parts.append(nxt)
                    idx.add(j)
                else:
                    break
            return " ".join(parts), idx
    return None, set()


def extract_heading(text: str, max_lines: int = 25) -> str | None:
    """Tiêu đề văn bản (xem find_heading)."""
    return find_heading(text.split("\n"), max_lines)[0]


def extract_issued_date(text: str, max_lines: int = 30) -> str | None:
    """Ngày ban hành ISO `YYYY-MM-DD` nếu phần đầu văn bản có "ngày D tháng M năm Y" đầy đủ, ngược lại None."""
    m = DATE_RE.search("\n".join(text.split("\n")[:max_lines]))
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    if not (1 <= d <= 31 and 1 <= mo <= 12 and 2000 <= y <= 2100):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


@dataclass
class FilterResult:
    """Kết quả lọc: `ftext` là văn bản đã bỏ phần thủ tục; `segs` ánh xạ vị trí ftext → vị trí gốc."""

    ftext: str
    segs: list[tuple[int, int, int]]  # (vị trí trong ftext, vị trí trong gốc, độ dài)
    removed: list[tuple[int, int, str]] = field(default_factory=list)  # (start, end, nhãn) theo tọa độ gốc
    warnings: list[str] = field(default_factory=list)
    heading: str | None = None
    preamble: tuple[int, int] | None = None  # theo tọa độ ftext

    def to_doc(self, fs: int, fe: int) -> tuple[int, int]:
        """Đổi khoảng [fs, fe) của ftext về khoảng [start, end) của văn bản gốc."""
        def find(p: int) -> tuple[int, int, int]:
            for seg in self.segs:
                if seg[0] <= p < seg[0] + seg[2]:
                    return seg
            return self.segs[-1]
        a = find(fs)
        b = find(max(fe - 1, fs))
        return a[1] + (fs - a[0]), b[1] + (max(fe - 1, fs) - b[0]) + 1

    def removed_chars(self) -> dict[str, int]:
        """Số ký tự đã bỏ theo từng nhãn (để ghi log)."""
        out: dict[str, int] = {}
        for s, e, lab in self.removed:
            out[lab] = out.get(lab, 0) + (e - s)
        return out


def _footer_too_big(lines: list[str], i: int, j: int) -> bool:
    nonblank = sum(1 for k in range(i, j) if lines[k].strip())
    chars = sum(len(lines[k]) + 1 for k in range(i, j))
    return nonblank > FOOTER_MAX_LINES or chars > FOOTER_MAX_CHARS


def filter_document(text: str) -> FilterResult:
    """Bỏ phần thủ tục của văn bản; xem docstring module."""
    lines = text.split("\n")
    offs, p = [], 0
    for l in lines:
        offs.append(p)
        p += len(l) + 1
    n = len(lines)
    drop: dict[int, str] = {}
    warnings: list[str] = []
    for i, l in enumerate(lines[:40]):
        if is_boiler_line(l):
            drop[i] = "khung_hanh_chinh"
    for i, l in enumerate(lines):  # tài liệu gồm nhiều văn bản nối nhau: khung đầu của văn bản sau cũng bỏ
        if i not in drop and is_strict_boiler(l):
            drop[i] = "khung_hanh_chinh"
    heading, hidx = find_heading(lines)
    for i in hidx:
        drop[i] = "tieu_de"
    for i, l in enumerate(lines):
        if DECIDE.match(l):
            drop[i] = "dau_de_quyet_dinh"
        elif JUNK_NUM.match(l):
            drop[i] = "so_roi_rac"
        if NOI_NHAN.match(l):
            j = i + 1
            while j < n:
                s = lines[j].strip()
                if s and (ATTACH.match(s) or len(s) >= 90 or is_strict_boiler(s) or CAN_CU.match(s) or DECIDE.match(s)
                          or (KIND.match(s) and s.upper() == s)):  # gặp đầu văn bản kế tiếp thì dừng
                    break
                j += 1
            if _footer_too_big(lines, i, j):
                warnings.append(f"khối 'Nơi nhận' dòng {i + 1}-{j} quá lớn (>{FOOTER_MAX_CHARS} ký tự hoặc >{FOOTER_MAX_LINES} dòng): GIỮ NGUYÊN")
            else:
                for k in range(i, j):
                    drop[k] = "noi_nhan_chu_ky"
    for i, l in enumerate(lines):  # chữ ký đứng giữa tài liệu (văn bản nối nhau): chức danh viết hoa + tối đa 3 dòng ngắn (tên)
        ls = l.strip()
        if i in drop or not (SIGN.match(l) and ls.upper() == ls and len(ls) <= 40):
            continue
        blk, j, cnt = [i], i + 1, 0
        while j < n and cnt < 3:
            t = lines[j].strip()
            if not t:
                j += 1
                continue
            if len(t) > 35 or t.endswith((".", ":", ";")) and not re.match(r"^(ts|ths|pgs|gs|ks|cn)\.", t, re.I) or ATTACH.match(t) or CAN_CU.match(t):
                break
            blk.append(j)
            cnt += 1
            j += 1
        for k in blk:
            drop.setdefault(k, "noi_nhan_chu_ky")
    for i in range(1, n):  # chức danh ký đứng ngay trước "Nơi nhận"
        if drop.get(i) == "noi_nhan_chu_ky" and NOI_NHAN.match(lines[i]):
            k = i - 1
            while k >= 0 and not lines[k].strip():
                k -= 1
            if k >= 0 and k not in drop and SIGN.match(lines[k]) and lines[k].strip().upper() == lines[k].strip():
                for m_ in range(k, i):
                    drop.setdefault(m_, "noi_nhan_chu_ky")
    nonempty = [i for i, l in enumerate(lines) if l.strip()]
    for i in nonempty[-12:]:  # chữ ký không có "Nơi nhận"
        if i not in drop and SIGN.match(lines[i]) and lines[i].strip().upper() == lines[i].strip():
            if _footer_too_big(lines, i, n):
                warnings.append(f"khối chữ ký dòng {i + 1}-{n} quá lớn: GIỮ NGUYÊN")
            else:
                for k in range(i, n):
                    drop.setdefault(k, "noi_nhan_chu_ky")
            break
    # preamble: khối "Căn cứ..." đầu tiên (trong 60 dòng đầu, chưa bị bỏ)
    pre = None
    for i in range(min(n, 60)):
        if i not in drop and CAN_CU.match(lines[i]):
            j, last = i, i
            while j < n and j not in drop and lines[j].strip().lower() != "quyết định:":
                s = lines[j].strip()
                prev_end = lines[last].rstrip().endswith((";", ".", ":"))
                if not s:
                    j += 1
                    continue
                if CAN_CU.match(s) or not prev_end:
                    last = j
                    j += 1
                else:
                    break
            pre = (i, last)
            break
    keep_lines = [i for i in range(n) if i not in drop]
    parts, segs, removed = [], [], []
    fpos = 0
    pre_f: list[int] = []
    for i in keep_lines:
        seg_text = lines[i] + ("\n" if i < n - 1 else "")
        if segs and segs[-1][1] + segs[-1][2] == offs[i]:
            segs[-1] = (segs[-1][0], segs[-1][1], segs[-1][2] + len(seg_text))
        else:
            segs.append((fpos, offs[i], len(seg_text)))
        if pre and pre[0] <= i <= pre[1]:
            pre_f.append(fpos)
            pre_end = fpos + len(lines[i])
        parts.append(seg_text)
        fpos += len(seg_text)
    for i in sorted(drop):
        removed.append((offs[i], offs[i] + len(lines[i]) + 1, drop[i]))
    ftext = "".join(parts)
    pre_span = (pre_f[0], pre_end) if pre_f else None
    if not segs:
        segs = [(0, 0, 0)]
    return FilterResult(ftext, segs, removed, heading=heading, preamble=pre_span, warnings=warnings)

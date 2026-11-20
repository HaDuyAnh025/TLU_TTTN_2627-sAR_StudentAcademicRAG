"""Parser tờ rơi (parser_mode = brochure_by_page): mỗi TRANG là một mục; tiêu đề mục = "<tên ngành> (<mã ngành>)" trích từ đầu trang.

Không nhận dòng viết hoa làm heading (tờ rơi có nhiều chú thích ảnh viết hoa như "PHIÊN TÒA GIẢ ĐỊNH SỐ 05"). Trang không có ngành thì tiêu đề mục là
"Trang N".
"""
from __future__ import annotations

import re

from .base import Section

RE_ANCHOR = re.compile(r"Thang\s*Long\s*University", re.I)
RE_MA = re.compile(r"Mã\s*xét\s*tuy\w{1,2}n", re.I)  # OCR hay đọc "tuyển" thành "tuyến"/"tuyên"/"tuyền"
RE_CODE = re.compile(r"(?<![\w])(\d{7}[A-Z]?)(?![\w])")
RE_INFO_TABLE = re.compile(r"Chương\s*trình|Số\s*lượng", re.I)  # bảng tổng hợp "Mã xét tuyển | Chương trình đào tạo | ... | Số lượng tuyển sinh"
RE_LEAD_NUM = re.compile(r"^\d{1,3}\s+")
RE_NEW = re.compile(r"\s+(MỚI|NEW)\s*$", re.I)


def program_parts(page_text: str) -> tuple[str, str] | None:
    """(tên ngành, mã) từ đầu trang; None nếu không xác định được cả tên lẫn mã."""
    lines = [l.strip() for l in page_text.split(chr(10)) if l.strip()][:16]
    # dòng tiêu đề "Mã xét tuyển ..." của trang ngành (không phải dòng của một bảng tổng hợp "| Mã xét tuyển | Chương trình ... |")
    m = next((i for i, l in enumerate(lines) if RE_MA.search(l) and not l.startswith("|") and not RE_INFO_TABLE.search(l)), None)
    if m is None:
        return None
    code = next((c.group(1) for l in lines[m:m + 4] if (c := RE_CODE.search(l))), None)
    names: list[str] = []
    for l in reversed(lines[:m]):  # đi ngược từ dòng "Mã xét tuyển" tới dòng "Thang Long University" (không gồm)
        if RE_ANCHOR.search(l):
            break
        names.insert(0, l)
    cand = [l for l in names if not (l.upper() == l and len(l) > 3)] or names  # bỏ chú thích ảnh viết hoa toàn bộ ("PHIÊN TÒA GIẢ ĐỊNH SỐ 05")
    if not cand:
        return None
    name = cand[-1]  # tên ngành là dòng sát "Mã xét tuyển" nhất; dòng đó viết thường đầu dòng thì là phần nối của dòng trước nó
    if name[:1].islower() and len(cand) > 1:
        name = cand[-2] + " " + name
    name = RE_NEW.sub("", RE_LEAD_NUM.sub("", name)).strip()
    if len(name.split()) < 1 or len(name) < 3 or not code:
        return None
    return name, code


def program_of(page_text: str) -> str | None:
    """"<tên ngành> (<mã 7 chữ số + chữ cái tùy chọn>)" từ đầu trang (tên gốc, chưa ghép danh mục); None nếu không xác định được."""
    pc = program_parts(page_text)
    return f"{pc[0]} ({pc[1]})" if pc else None


def ftext_pos(fr, pos: int) -> int:
    """Vị trí `pos` của văn bản gốc -> vị trí tương ứng trong ftext (phần bị lọc thì lấy đầu đoạn giữ lại kế tiếp)."""
    for ft, orig, n in fr.segs:
        if pos < orig + n:
            return ft + max(0, pos - orig)
    return len(fr.ftext)


def brochure_sections(doc, fr, catalog=None, bac=None, log=None) -> list[Section]:
    """Section theo trang (tọa độ ftext). Trang rỗng sau khi lọc bị bỏ."""
    pages = []
    for i, sp in enumerate(doc.spans):
        pages.append((ftext_pos(fr, sp.start), sp.page if sp.page is not None else i + 1, doc.text[sp.start:sp.end]))
    pages.sort(key=lambda x: x[0])
    out: list[Section] = []
    for k, (start, page, text) in enumerate(pages):
        end = pages[k + 1][0] if k + 1 < len(pages) else len(fr.ftext)
        if end <= start or not fr.ftext[start:end].strip():
            continue
        pc = program_parts(text)
        ten = ma = ma_goc = None
        if pc and catalog is not None and catalog.entries:
            m = catalog.resolve(pc[0], pc[1], bac)  # ghép danh mục theo MÃ: sửa lỗi OCR như "Kế toàn" -> "Kế toán"
            if log is not None:
                log.append(m)
            ten, ma, ma_goc = m.ten, m.ma, m.nganh_goc
        elif pc:
            ten, ma = pc
        title = f"Ngành {ten} ({ma})" if ten else f"Trang {page}"  # cùng dạng với khung CTĐT: "Ngành <tên chuẩn> (<mã>)"
        out.append(Section("section", start, end, f"pg{page}", f"pg{page}", crumb=[title], nganh_ma=ma, nganh_ten=ten, nganh_ma_goc=ma_goc))
    return out

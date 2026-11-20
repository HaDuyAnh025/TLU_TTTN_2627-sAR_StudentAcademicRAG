"""Dòng bảng -> câu tiếng Việt tự đứng được, theo doc_type; không có template phù hợp thì dùng mẫu chung.

Giữ NGUYÊN giá trị ô (số tiền, mã môn, đơn vị) như trong bảng. Ô trống bị bỏ cụm tương ứng, không ghi "None"/"nan".
"""
from __future__ import annotations

import re
from typing import Callable

from .extract import Row

# field -> các regex (theo thứ tự ưu tiên) áp lên tên cột đã chuẩn hóa (viết thường)
SPECS: dict[str, list[tuple[str, list[str]]]] = {
    "hoc_phi": [
        ("he", [r"hệ", r"loại hình", r"chương trình", r"bậc"]),
        ("doi_tuong", [r"đối tượng", r"khóa|khoá", r"ngành", r"nhóm"]),
        ("nam_hoc", [r"năm học"]),
        ("muc", [r"mức thu", r"số tiền|mức|đơn giá|thành tiền", r"học phí|lệ phí"]),
        ("don_vi", [r"đơn vị|đvt"]),
    ],
    "hoc_bong": [
        ("loai", [r"loại học bổng", r"học bổng", r"loại", r"tên"]),
        ("dieu_kien", [r"điều kiện|tiêu chí|yêu cầu"]),
        ("muc", [r"mức|giá trị|số tiền"]),
        ("so_suat", [r"số suất|suất|số lượng"]),
    ],
    "ctdt": [
        ("ten", [r"tên học phần|tên môn", r"(?<!mã )(học phần|môn học)"]),
        ("ma", [r"mã"]),
        ("tc", [r"số tc|tín chỉ|\btc\b|số tín"]),
        ("loai", [r"bắt buộc|tự chọn|tính chất|loại"]),
        ("hk", [r"học kỳ|học kì|\bhk\b|kỳ|kì"]),
        ("tq", [r"tiên quyết|học trước"]),
    ],
    "lich_thi": [
        ("ten", [r"tên môn|môn thi", r"(?<!mã )(môn|học phần|nội dung)"]),
        ("ma", [r"mã"]),
        ("lop", [r"lớp"]),
        ("ngay", [r"ngày"]),
        ("gio", [r"giờ|ca thi|\bca\b|thời gian"]),
        ("phong", [r"phòng|địa điểm"]),
        ("ht", [r"hình thức"]),
    ],
    "tkb": [
        ("lop", [r"lớp"]),
        ("ten", [r"tên môn|tên học phần|tên", r"(?<!mã )(môn học|học phần|môn)"]),
        ("ma", [r"mã"]),
        ("thu", [r"thứ", r"ngày"]),
        ("tiet", [r"tiết", r"giờ"]),
        ("phong", [r"phòng"]),
        ("gv", [r"giảng viên|\bgv\b"]),
    ],
}
REQUIRED = {"hoc_phi": [("muc",)], "hoc_bong": [("loai",), ("muc",)], "ctdt": [("ten",)], "lich_thi": [("ten",)], "tkb": [("lop",), ("ten",)]}


def resolve(doc_type: str, header: list[str]) -> dict[str, int]:
    """Ánh xạ field -> chỉ số cột (mỗi cột chỉ dùng một lần)."""
    used: set[int] = set()
    out: dict[str, int] = {}
    for field, pats in SPECS.get(doc_type, []):
        for pat in pats:
            idx = next((i for i, h in enumerate(header) if i not in used and re.search(pat, h.lower())), None)
            if idx is not None:
                out[field] = idx
                used.add(idx)
                break
    return out


def _opt(prefix: str, v: str, suffix: str = "") -> str:
    return f"{prefix}{v}{suffix}" if v else ""


def _unit_of(header_name: str) -> str:
    m = re.search(r"\(([^)]*)\)", header_name)
    return m.group(1).strip() if m else ""


def _hoc_phi(v: dict[str, str], hdr: dict[str, str]) -> str:
    unit = v.get("don_vi") or _unit_of(hdr.get("muc", ""))
    kind = "Lệ phí" if re.search(r"lệ phí", hdr.get("muc", ""), re.I) and not re.search(r"học phí", hdr.get("muc", ""), re.I) else "Học phí"
    return (kind + _opt(" ", v.get("he", "")) + _opt(" cho ", v.get("doi_tuong", "")) + _opt(", năm học ", v.get("nam_hoc", ""))
            + ": " + v["muc"] + _opt(" ", unit))


FORMATTERS: dict[str, Callable[[dict[str, str], dict[str, str]], str]] = {
    "hoc_phi": _hoc_phi,
    "hoc_bong": lambda v, h: ("Học bổng" + _opt(" ", v.get("loai", "")) + _opt(" dành cho sinh viên có ", v.get("dieu_kien", ""))
                              + _opt(", mức ", v.get("muc", "")) + _opt(", số suất ", v.get("so_suat", ""))),
    "ctdt": lambda v, h: ("Học phần " + v["ten"] + _opt(" (", v.get("ma", ""), ")") + _opt(", ", v.get("tc", ""), " tín chỉ")
                          + _opt(", ", v.get("loai", "")) + _opt(", học kỳ ", v.get("hk", "")) + _opt(", tiên quyết: ", v.get("tq", ""))),
    "lich_thi": lambda v, h: ("Môn " + v.get("ten", "") + _opt(" (", v.get("ma", ""), ")") + _opt(", lớp ", v.get("lop", ""))
                              + _opt(", thi ngày ", v.get("ngay", "")) + _opt(" lúc ", v.get("gio", ""))
                              + _opt(", phòng ", v.get("phong", "")) + _opt(", hình thức ", v.get("ht", ""))),
    "tkb": lambda v, h: ("Lớp " + v.get("lop", "") + _opt(" học ", v.get("ten", "")) + _opt(" (", v.get("ma", ""), ")")
                         + _opt(" vào ", v.get("thu", "")) + _opt(", tiết ", v.get("tiet", "")) + _opt(", phòng ", v.get("phong", ""))
                         + _opt(", giảng viên ", v.get("gv", ""))),
}


def generic_sentence(header: list[str], cells: list[str], skip: set[int] = frozenset()) -> str:
    """"{Cột 1}: {giá trị 1}; {Cột 2}: {giá trị 2}" — bỏ ô trống."""
    return "; ".join(f"{h}: {c}" for i, (h, c) in enumerate(zip(header, cells)) if c and i not in skip)


def row_sentence(doc_type: str, header: list[str], row: Row) -> str:
    """Một câu hoàn chỉnh cho 1 dòng. Dòng nhãn nhóm (nếu có) được đặt đầu câu."""
    cols = resolve(doc_type, header)
    sent = ""
    used: set[int] = set()
    if doc_type in FORMATTERS and all(any(f in cols and row.cells[cols[f]] for f in alt) for alt in REQUIRED[doc_type]):
        vals = {f: row.cells[i] for f, i in cols.items() if row.cells[i]}
        hdr = {f: header[i] for f, i in cols.items()}
        if doc_type == "hoc_phi" and "muc" not in vals:
            sent = ""
        else:
            sent = FORMATTERS[doc_type](vals, hdr)
            used = {i for f, i in cols.items() if row.cells[i]}
    if sent:
        extra = generic_sentence(header, row.cells, used)
        sent = sent + ("; " + extra if extra else "")
    else:
        sent = generic_sentence(header, row.cells)
    if row.label:
        sent = f"{row.label}: {sent}"
    return sent.rstrip(" .;") + "."

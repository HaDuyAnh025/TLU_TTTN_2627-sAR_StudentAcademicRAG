"""Quy tắc chuẩn hóa theo miền (học kỳ, năm học, khóa), DÙNG CHUNG cho BM25 (lúc index và lúc truy vấn) và query_parser.

Chỉ regex thuần, không import nặng. Mọi hàm nhận văn bản bất kỳ (tự NFC + chữ thường).
Token chuẩn: hk1 | hk2 | hk3 | hkphu | hkhe ; nh_2025_2026 (kèm 2025, 2026) ; khoa_38.
"""
from __future__ import annotations

import re
import unicodedata

KHOA_MIN, KHOA_MAX = 20, 60  # khóa hợp lệ; tránh nhận nhầm "k12", "k 99"
_NUM = {"i": 1, "ii": 2, "iii": 3, "1": 1, "2": 2, "3": 3}
_PREFIX = r"(?:học\s*k[ỳìy]|k[ỳì]|hk)"
HK_NUM_RE = re.compile(rf"(?<!\w){_PREFIX}\s*(?:thứ\s*)?(iii|ii|i|3|2|1)(?!\w)")
HK_NAMED_RE = re.compile(rf"(?<!\w){_PREFIX}\s*(phụ|hè)(?!\w)")
NH_RE = re.compile(r"(?<!\d)(20\d{2})\s*(?:[-–—]|/(?=20))\s*(20\d{2})(?!\d)")
KHOA_RE = re.compile(r"(?<!\w)(?:khóa|khoá|k)\s*(\d{2}(?:\s*(?:,|;|và|hoặc|/)\s*\d{2})*)(?!\w)")


def prep(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def find_hoc_ky(text: str) -> list[str]:
    """Các học kỳ trong văn bản theo thứ tự xuất hiện: hk1/hk2/hk3/hkphu/hkhe."""
    t = prep(text)
    hits = [(m.start(), f"hk{_NUM[m.group(1)]}") for m in HK_NUM_RE.finditer(t)]
    hits += [(m.start(), "hkphu" if m.group(1) == "phụ" else "hkhe") for m in HK_NAMED_RE.finditer(t)]
    return [h for _, h in sorted(hits)]


def find_nam_hoc(text: str) -> list[tuple[int, int]]:
    return [(int(m.group(1)), int(m.group(2))) for m in NH_RE.finditer(prep(text))]


def find_khoa(text: str) -> list[int]:
    """Các khóa trong văn bản (giữ thứ tự, bỏ trùng): "khóa 38", "K38", "K35, 36, 37"."""
    out: list[int] = []
    for m in KHOA_RE.finditer(prep(text)):
        for n in re.findall(r"\d{2}", m.group(1)):
            k = int(n)
            if KHOA_MIN <= k <= KHOA_MAX and k not in out:
                out.append(k)
    return out


def domain_tokens(text: str) -> list[str]:
    """Token chuẩn hóa (thêm vào BM25, KHÔNG thay từ gốc)."""
    out = list(dict.fromkeys(find_hoc_ky(text)))
    for a, b in find_nam_hoc(text):
        out += [f"nh_{a}_{b}", str(a), str(b)]
    out += [f"khoa_{k}" for k in find_khoa(text)]
    return out

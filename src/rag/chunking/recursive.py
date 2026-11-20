"""Recursive splitter có overlap, giữ char offset: đoạn → dòng → câu → từ → ký tự."""
from __future__ import annotations

import re

from .tokenizer import count_tokens

# Mỗi mức: regex nhận diện điểm cắt (phần khớp thuộc về mảnh đứng trước).
_LEVELS = [re.compile(r"\n\s*\n"), re.compile(r"\n"), re.compile(r"(?<=[.!?;:])\s+"), re.compile(r"\s+")]


def _strip_span(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _pieces(text: str, s: int, e: int, level: int) -> list[tuple[int, int]]:
    cuts, last = [], s
    for m in _LEVELS[level].finditer(text, s, e):
        if m.end() > last and m.end() < e:
            cuts.append((last, m.end()))
            last = m.end()
    cuts.append((last, e))
    return cuts


def _units(text: str, s: int, e: int, limit: int, level: int = 0) -> list[tuple[int, int]]:
    """Cắt [s, e) thành các đơn vị liền kề, mỗi đơn vị <= limit token (nếu có thể)."""
    if count_tokens(text[s:e]) <= limit:
        return [(s, e)]
    if level >= len(_LEVELS):  # từ quá dài: cắt đều theo ký tự
        k = count_tokens(text[s:e]) // limit + 1
        step = max(1, (e - s) // k + 1)
        return [(i, min(i + step, e)) for i in range(s, e, step)]
    parts = _pieces(text, s, e, level)
    if len(parts) == 1:
        return _units(text, s, e, limit, level + 1)
    out: list[tuple[int, int]] = []
    for ps, pe in parts:
        out.extend(_units(text, ps, pe, limit, level + 1))
    return out


def split_recursive(text: str, start: int, end: int, max_tokens: int, overlap_ratio: float = 0.15) -> list[tuple[int, int]]:
    """Cắt text[start:end] thành các khoảng (s, e) tuyệt đối, mỗi khoảng <= max_tokens token.

    Các khoảng liền nhau chồng lên nhau khoảng `overlap_ratio * max_tokens` token (ở ranh giới đơn vị).
    Nếu cả đoạn đã vừa thì trả đúng 1 khoảng (không overlap). Khoảng luôn được cắt bỏ khoảng trắng đầu/cuối.
    """
    s0, e0 = _strip_span(text, start, end)
    if s0 >= e0:
        return []
    units: list[tuple[int, int]] = []
    for a, b in _units(text, s0, e0, max_tokens):
        if units and not text[a:b].strip():  # mảnh chỉ có khoảng trắng: nhập vào mảnh trước
            units[-1] = (units[-1][0], b)
        else:
            units.append((a, b))
    if len(units) == 1:
        return [(s0, e0)]
    overlap = int(max_tokens * overlap_ratio)
    out: list[tuple[int, int]] = []
    i = 0
    n = len(units)
    while i < n:
        j = i
        while j + 1 < n and count_tokens(text[units[i][0]:units[j + 1][1]]) <= max_tokens:
            j += 1
        out.append(_strip_span(text, units[i][0], units[j][1]))
        if j >= n - 1:
            break
        k = j + 1  # chỉ số đơn vị bắt đầu của mảnh kế tiếp
        while k - 1 > i and count_tokens(text[units[k - 1][0]:units[j][1]]) <= overlap:
            k -= 1
        if k == j + 1 and j > i and count_tokens(text[units[j][0]:units[j][1]]) <= 2 * overlap:
            k = j  # đơn vị cuối hơi lớn hơn ngưỡng nhưng vẫn lấy làm overlap (tối đa 2x) để không mất ngữ cảnh
        i = max(k, i + 1)
    return out

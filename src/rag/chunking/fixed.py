"""C1: cắt cố định 512 token, overlap 50 token (cl100k_base), không breadcrumb, giữ nguyên văn bản."""
from __future__ import annotations

from .tokenizer import _enc, count_tokens


def fixed_windows(text: str, max_tokens: int, overlap: int) -> list[tuple[int, int]]:
    """Các khoảng ký tự (start, end) của cửa sổ cố định theo token; nội dung = text[start:end], <= max_tokens token."""
    enc = _enc()
    toks = enc.encode(text)
    if not toks:
        return []
    _, offs = enc.decode_with_offsets(toks)
    offs = list(offs)
    for i in range(1, len(offs)):  # token cắt giữa ký tự UTF-8 có thể cho offset lùi: ép đơn điệu
        offs[i] = max(offs[i], offs[i - 1])
    n, step = len(toks), max_tokens - overlap
    out: list[tuple[int, int]] = []
    i = 0
    while i < n:
        j = min(i + max_tokens, n)
        s = offs[i]
        e = offs[j] if j < n else len(text)
        while j > i + 1 and count_tokens(text[s:e]) > max_tokens:  # hiếm: đếm lại sau khi cắt có thể lệch
            j -= 1
            e = offs[j]
        if text[s:e].strip():
            out.append((s, e))
        if j >= n:
            break
        i = max(i + 1, j - overlap) if j - overlap > i else j
    return out

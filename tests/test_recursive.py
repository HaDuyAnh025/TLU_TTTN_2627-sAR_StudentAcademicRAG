"""Recursive splitter: giữ offset, không vượt giới hạn, có overlap khi phải cắt."""
from __future__ import annotations

from rag.chunking.fixed import fixed_windows
from rag.chunking.recursive import split_recursive
from rag.chunking.tokenizer import count_tokens

TEXT = "\n\n".join(" ".join(f"Câu số {p}-{i} nói về quy định đăng ký học phần của sinh viên." for i in range(12)) for p in range(8))


def test_short_text_single_span_no_overlap():
    t = "Một đoạn ngắn."
    assert split_recursive(t, 0, len(t), 512) == [(0, len(t))]


def test_pieces_within_limit_and_overlap():
    spans = split_recursive(TEXT, 0, len(TEXT), 120, 0.15)
    assert len(spans) > 3
    for s, e in spans:
        assert count_tokens(TEXT[s:e]) <= 120
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert s2 < e1 and s2 > s1  # chồng lên nhau, vẫn tiến về trước
    assert spans[0][0] == 0 and spans[-1][1] == len(TEXT)


def test_fixed_windows_limit_and_coverage():
    spans = fixed_windows(TEXT, 100, 20)
    assert all(count_tokens(TEXT[s:e]) <= 100 for s, e in spans)
    assert spans[0][0] == 0 and spans[-1][1] == len(TEXT)
    assert all(s2 < e1 for (_, e1), (s2, _) in zip(spans, spans[1:]))

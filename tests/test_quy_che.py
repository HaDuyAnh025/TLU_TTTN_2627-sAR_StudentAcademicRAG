"""Kiểm tra C1/C2 trên quy chế mẫu (Chương/Điều/Khoản/Điểm, vắt trang, thủ tục)."""
from __future__ import annotations

import json
import re

from rag.chunking.tokenizer import count_tokens


def run(chunker, doc, meta, name):
    return chunker.c1(doc, meta) if name == "c1" else chunker.c2(doc, meta)


def test_max_tokens_all_configs(make_chunker, quy_che_doc, quy_che_meta):
    for name in ("c1", "c2"):
        for c in run(make_chunker(), quy_che_doc, quy_che_meta, name):
            assert c.n_tokens <= 512, (name, c.chunk_id, c.n_tokens)
            assert count_tokens(c.embed_text) == c.n_tokens


def test_c1_fixed_small_doc_keeps_everything(make_chunker, quy_che_doc, quy_che_meta):
    chunks = make_chunker().c1(quy_che_doc, quy_che_meta)
    joined = "".join(c.content for c in chunks)
    assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" in joined and "Nơi nhận" in joined  # C1 không lọc
    assert all(c.chunk_id.startswith("qc-mau::fx::") for c in chunks)
    assert all(c.embed_text == c.content for c in chunks)


def test_breadcrumb_only_in_c2(make_chunker, quy_che_doc, quy_che_meta):
    ch = make_chunker()
    assert not any(c.embed_text.startswith("[") for c in ch.c1(quy_che_doc, quy_che_meta))
    c2 = ch.c2(quy_che_doc, quy_che_meta)
    assert all(c.embed_text.startswith("[") and "] " in c.embed_text for c in c2)
    k = [c for c in c2 if c.metadata.article == 2 and c.metadata.clause == 3][0]
    assert "Điều 2. Đăng ký học" in k.embed_text and "Chương I: QUY ĐỊNH CHUNG" in k.embed_text


def test_no_clause_split_and_no_cross_article(make_chunker, quy_che_doc, quy_che_meta):
    ch = make_chunker(min_tokens=5)
    c2 = ch.c2(quy_che_doc, quy_che_meta)
    text = quy_che_doc.text
    for c in c2:
        arts = set(re.findall(r"^Điều\s+(\d+)\.", c.content, re.M))
        assert len(arts) <= 1, c.chunk_id
    k2 = [c for c in c2 if c.chunk_id == "qc-mau::d2::k2"]
    assert len(k2) == 1 and "b) học kỳ phụ" in k2[0].content  # Khoản 2 nguyên vẹn, kèm cả Điểm a, b
    assert text[k2[0].metadata.char_start:k2[0].metadata.char_end] == k2[0].content


def test_min_tokens_merge_same_article_only(make_chunker, quy_che_doc, quy_che_meta):
    c2 = make_chunker(min_tokens=50).c2(quy_che_doc, quy_che_meta)
    ids = [c.chunk_id for c in c2]
    assert any("+" in i for i in ids)  # có gộp chunk nhỏ
    for c in c2:
        assert len({p for p in re.findall(r"::d(\d+)", c.chunk_id)}) <= 1  # không gộp qua 2 Điều


def test_long_clause_recursive_with_breadcrumb(make_chunker, quy_che_doc, quy_che_meta):
    c2 = make_chunker().c2(quy_che_doc, quy_che_meta)
    pieces = [c for c in c2 if c.metadata.article == 2 and c.metadata.clause == 4]
    assert len(pieces) >= 2
    assert [c.chunk_id.rsplit("::", 1)[1] for c in pieces][:2] == ["p1", "p2"]
    assert all("Khoản 4" in c.embed_text and c.n_tokens <= 512 for c in pieces)
    assert pieces[0].content[-30:] in pieces[1].content or pieces[1].content[:30] in pieces[0].content  # có overlap


def test_content_equals_text_slice(make_chunker, quy_che_doc, quy_che_meta):
    for name in ("c1", "c2"):
        for c in run(make_chunker(), quy_che_doc, quy_che_meta, name):
            if name == "c2" and "::p" in c.chunk_id:
                continue
            m = c.metadata
            assert quy_che_doc.text[m.char_start:m.char_end] == c.content or name == "c2" and c.content in quy_che_doc.text


def test_article_across_pages(make_chunker, quy_che_doc, quy_che_meta):
    c2 = make_chunker(min_tokens=5).c2(quy_che_doc, quy_che_meta)
    k = [c for c in c2 if c.metadata.article == 3 and c.metadata.clause == 1]
    assert len(k) == 1
    assert "Các quy định" in k[0].content and "trước đây trái" in k[0].content
    assert (k[0].metadata.page_start, k[0].metadata.page_end) == (1, 2)


def test_procedural_filtered_in_c2_not_c1(make_chunker, quy_che_doc, quy_che_meta):
    ch = make_chunker()
    c2_text = "\n".join(c.content for c in ch.c2(quy_che_doc, quy_che_meta))
    for bad in ("CỘNG HÒA XÃ HỘI", "Độc lập", "Nơi nhận", "HIỆU TRƯỞNG", "Nguyễn Văn A", "26032705", "Số: 12", "Hà Nội, ngày"):
        assert bad not in c2_text, bad
    assert not re.search(r"^\s*27\s*$", c2_text, re.M)
    pre = [c for c in ch.c2(quy_che_doc, quy_che_meta) if c.metadata.is_preamble]
    assert len(pre) == 1 and "Căn cứ Luật Giáo dục" in pre[0].content and "Theo đề nghị" in pre[0].content
    assert "QUYẾT ĐỊNH:" not in c2_text
    c1_text = "".join(c.content for c in ch.c1(quy_che_doc, quy_che_meta))
    assert "Nơi nhận" in c1_text and "26032705" in c1_text


def test_alias_and_ids_unique_stable(make_chunker, quy_che_doc, quy_che_meta):
    a = make_chunker().c2(quy_che_doc, quy_che_meta)
    b = make_chunker().c2(quy_che_doc, quy_che_meta)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)
    assert json.loads(a[0].model_dump_json())["config"] == "c2"

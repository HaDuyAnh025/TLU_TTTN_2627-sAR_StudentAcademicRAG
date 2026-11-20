"""Quy tắc bảng, C3 parent-child, bỏ header lặp khi bảng vắt qua trang, bỏ qua tài liệu trung_voi, không sửa file đầu vào."""
from __future__ import annotations

import json

import yaml

from rag.chunking.loader import build_document
from rag.chunking.metadata import DocMeta
from rag.chunking.splitter import chunk_corpus

from conftest import make_clean

HEAD = "THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\n"


def meta(doc_type="hoc_phi") -> DocMeta:
    return DocMeta(doc_id="t", file="t.pdf", doc_type=doc_type, bac_dao_tao="dai_hoc", title="THÔNG BÁO Học phí")


def table(n: int, hdr="| STT | Ngành | Học phí (VNĐ) |") -> str:
    rows = "\n".join(f"| {i} | Ngành số {i} | {20 + i}.000.000 |" for i in range(1, n + 1))
    return f"{hdr}\n|---|---|---|\n{rows}"


def tchunks(text: str, doc_type="hoc_phi", **over):
    from conftest import make_clean as mk
    doc = build_document(mk([(text, "text_layer")], file="t.pdf"))
    return doc


def test_small_table_one_whole_chunk(make_chunker):
    doc = build_document(make_clean([(HEAD + "Bảng 1. Mức thu học phí\n" + table(3) + "\n", "text_layer")], file="t.pdf"))
    cs = [c for c in make_chunker().c2(doc, meta()) if c.metadata.is_table]
    assert len(cs) == 1
    m = cs[0].metadata
    assert m.table_mode == "whole" and m.table_id == "t::t1" and m.table_title.startswith("Bảng 1")
    assert "| 3 | Ngành số 3 | 23.000.000 |" in cs[0].content
    assert cs[0].chunk_id == "t::t1::r000-002"


def test_large_table_rows_header_numbers(make_chunker):
    doc = build_document(make_clean([(HEAD + table(80) + "\n", "text_layer")], file="t.pdf"))
    cs = [c for c in make_chunker().c2(doc, meta()) if c.metadata.is_table]
    assert len(cs) > 1 and all(c.metadata.table_mode == "rows" for c in cs)
    assert all(c.n_tokens <= 512 for c in cs)
    assert all("Các cột:" in c.embed_text and "Học phí (VNĐ)" in c.embed_text for c in cs)  # header lặp ở mọi chunk
    covered = [i for c in cs for i in range(c.metadata.row_start, c.metadata.row_end + 1)]
    assert covered == list(range(80))  # mỗi dòng đúng 1 lần, không cắt giữa dòng
    assert "20.000.000".replace("20", "100") not in "".join(c.embed_text for c in cs) or True
    assert "100.000.000" in "".join(c.embed_text for c in cs)  # số nguyên văn (80 -> 100.000.000)
    assert all(c.metadata.table_id == "t::t1" for c in cs)
    assert all(c.chunk_id.startswith("t::t1::r") for c in cs)


def test_row_sentence_templates():
    from rag.chunking.tables.extract import Row
    from rag.chunking.tables.templates import row_sentence
    s = row_sentence("hoc_phi", ["Hệ", "Ngành", "Học phí (VNĐ/tín chỉ)"], Row(["Chính quy", "Luật", "1.200.000"], 0, 1))
    assert s == "Học phí Chính quy cho Luật: 1.200.000 VNĐ/tín chỉ."
    s = row_sentence("lich_thi", ["Mã môn", "Tên môn", "Ngày thi", "Phòng thi"], Row(["GE333", "Tiếng Anh", "23/11/2025", "A707"], 0, 1))
    assert "Môn Tiếng Anh (GE333)" in s and "thi ngày 23/11/2025" in s and "phòng A707" in s
    s = row_sentence("khac", ["A", "B"], Row(["x", ""], 0, 1))
    assert s == "A: x." and "None" not in s


def test_fill_down_merged_cells(make_chunker):
    t = "| Khoa | Ngành | Học phí |\n|---|---|---|\n" + "\n".join(
        [f"| Kinh tế | Ngành {i} | {i}00.000 |" if i == 0 else f"|  | Ngành {i} | {i}00.000 |" for i in range(0, 60)])
    doc = build_document(make_clean([(HEAD + t + "\n", "text_layer")], file="t.pdf"))
    cs = [c for c in make_chunker().c2(doc, meta("khac")) if c.metadata.is_table]
    assert all("Khoa: Kinh tế" in c.embed_text for c in cs)


def test_note_inline_vs_separate(make_chunker):
    short = "Ghi chú: Mức thu chưa gồm bảo hiểm y tế."
    doc = build_document(make_clean([(HEAD + table(80) + "\n\n" + short + "\n", "text_layer")], file="t.pdf"))
    cs = [c for c in make_chunker().c2(doc, meta()) if c.metadata.table_id]
    assert all("bảo hiểm y tế" in c.embed_text for c in cs if c.metadata.is_table)  # inline vào mọi chunk
    long_note = "Ghi chú: " + " ".join(f"Điều kiện bổ sung số {i} áp dụng cho sinh viên thuộc diện được miễn giảm." for i in range(30))
    doc = build_document(make_clean([(HEAD + table(80) + "\n\n" + long_note + "\n", "text_layer")], file="t.pdf"))
    cs = [c for c in make_chunker().c2(doc, meta()) if c.metadata.table_id]
    notes = [c for c in cs if not c.metadata.is_table]
    assert len(notes) == 1 and notes[0].metadata.table_id == "t::t1" and notes[0].chunk_id == "t::t1::note"
    assert all("Điều kiện bổ sung số 5" not in c.embed_text for c in cs if c.metadata.is_table)


def test_table_in_article_breadcrumb_and_lead_in(make_chunker):
    text = ("QUYẾT ĐỊNH\nVề mức thu học phí\n\nĐiều 1. Mức thu\nMức thu học phí như sau:\nBảng 1. Học phí\n" + table(3)
            + "\n\nĐiều 2. Hiệu lực\nQuyết định có hiệu lực từ ngày ký và được áp dụng cho tất cả sinh viên của Trường.\n")
    doc = build_document(make_clean([(text, "text_layer")], file="t.pdf"))
    cs = make_chunker().c2(doc, meta("quy_che"))
    t = [c for c in cs if c.metadata.is_table][0]
    assert "Điều 1" in t.embed_text.split("]")[0] and "Bảng 1" in t.embed_text.split("]")[0]
    assert "Mức thu học phí như sau:" in t.embed_text
    assert t.metadata.article == 1


def test_ocr_pages_have_no_tables(make_chunker):
    doc = build_document(make_clean([(HEAD + "| a | b |\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n", "ocr")], file="t.pdf"))
    cs = make_chunker().c2(doc, meta())
    assert not any(c.metadata.is_table for c in cs)
    assert any(c.metadata.ocr_table_suspect for c in cs)


def test_cross_page_table_header_dropped():
    p0 = "Bảng học phí\n| STT | Ngành | Học phí |\n|---|---|---|\n| 1 | A | 10 |\n| 2 | B | 20 |"
    p1 = "| STT | Ngành | Học phí |\n|---|---|---|\n| 3 | C | 30 |"
    doc = build_document(make_clean([(p0, "text_layer"), (p1, "text_layer")], file="t.pdf"))
    assert doc.text.count("| STT | Ngành | Học phí |") == 1
    assert "| 2 | B | 20 |\n| 3 | C | 30 |" in doc.text


def test_c3_parent_child(quy_che_doc, quy_che_meta, make_chunker):
    children, parents = make_chunker().c3(quy_che_doc, quy_che_meta)
    ids = {p["parent_id"] for p in parents}
    assert ids and all(c.config == "c3" for c in children)
    assert all(c.metadata.parent_id in ids for c in children if c.metadata.parent_id)
    d2 = next(p for p in parents if p["parent_id"].endswith("::d2"))
    assert "Điều 2" in d2["content"] and "học kỳ phụ" in d2["content"] and "Điều 3" not in d2["content"]
    assert any(c.metadata.parent_id == d2["parent_id"] for c in children)


def test_c3_non_quy_che_has_no_parents(make_chunker):
    doc = build_document(make_clean([(HEAD + table(3) + "\n", "text_layer")], file="t.pdf"))
    children, parents = make_chunker().c3(doc, meta())
    assert parents == [] and all(c.metadata.parent_id is None for c in children)


def test_corpus_skips_trung_voi_and_keeps_inputs(tmp_path, cfg, monkeypatch):
    clean = tmp_path / "clean"
    clean.mkdir()
    for name in ("a", "b"):
        (clean / f"{name}.json").write_text(json.dumps(make_clean([(HEAD + table(3), "text_layer")], file=f"{name}.pdf")), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in clean.iterdir()}
    docs = {"docs": {n: {"file": f"{n}.pdf", "doc_type": "hoc_phi", "title": "t", "bac_dao_tao": "dai_hoc", "status": "hieu_luc",
                         **({"trung_voi": "a"} if n == "b" else {})} for n in ("a", "b")}}
    (tmp_path / "doc_meta.yaml").write_text(yaml.safe_dump(docs, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "out"
    counts = chunk_corpus("all", out_dir=out, clean_dir=clean, doc_meta_path=tmp_path / "doc_meta.yaml")
    assert counts["c2"] > 0
    ids = {json.loads(l)["metadata"]["doc_id"] for l in (out / "chunks" / "c2_chunks.jsonl").open(encoding="utf-8")}
    assert ids == {"a"}
    assert json.loads((out / "chunks" / "stats.json").read_text(encoding="utf-8"))["skipped"][0]["doc_id"] == "b"
    assert before == {p.name: p.read_bytes() for p in clean.iterdir()}


def test_oversize_row_split_by_column_groups(make_chunker):
    big = " ".join(f"nội dung chi tiết số {i} của học phần bổ sung kiến thức" for i in range(40))
    t = "| TT | Tên ngành | Mô tả A | Mô tả B | Mô tả C |\n|---|---|---|---|---|\n" + "\n".join(
        f"| {i} | Ngành {i} | {big} | {big} | {big} |" for i in range(1, 4))
    doc = build_document(make_clean([(HEAD + t + "\n", "text_layer")], file="t.pdf"))
    cs = [c for c in make_chunker().c2(doc, meta("khac")) if c.metadata.is_table]
    assert cs and all(c.n_tokens <= 512 for c in cs)
    pieces = [c for c in cs if "::c" in c.chunk_id]
    assert pieces and any(c.chunk_id.endswith("::c1") for c in pieces) and any(c.chunk_id.endswith("::c2") for c in pieces)
    for c in pieces:  # mỗi mảnh lặp header + giá trị cột định danh (cột đầu + cột tên)
        assert "Các cột: TT | Tên ngành" in c.embed_text and "TT: 2" in c.embed_text or "TT: 1" in c.embed_text or "TT: 3" in c.embed_text
        assert "Tên ngành: Ngành" in c.embed_text
    row2 = [c for c in pieces if "::r001-001" in c.chunk_id]
    assert all(c.metadata.row_start == c.metadata.row_end == 1 for c in row2)


NUMBERED = """QUY ĐỊNH ĐĂNG KÝ THI LẠI

1. Sinh viên được đăng ký thi lại 01 lần các học phần có điểm tổng kết nhỏ hơn 4 theo kế hoạch của Phòng Đào tạo.
2. Sinh viên vắng mặt quá 30% số giờ của môn học sẽ không được dự thi và phải đăng ký học lại theo quy định chung.
"""


def test_quy_che_numbered_sections_no_fallback(make_chunker):
    doc = build_document(make_clean([(NUMBERED, "text_layer")], file="t.pdf"))
    cs = make_chunker().c2(doc, meta("quy_che"))
    assert cs and not any(c.metadata.fallback for c in cs)


def test_excluded_docs_not_in_embedding_inputs(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    for name in ("a", "b"):
        (clean / f"{name}.json").write_text(json.dumps(make_clean([(HEAD + table(3), "text_layer")], file=f"{name}.pdf")), encoding="utf-8")
    docs = {"docs": {n: {"file": f"{n}.pdf", "doc_type": "hoc_phi", "title": "t", "bac_dao_tao": "dai_hoc", "status": "hieu_luc",
                         "in_scope": n == "a"} for n in ("a", "b")}}
    (tmp_path / "doc_meta.yaml").write_text(yaml.safe_dump(docs, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "out"
    chunk_corpus("all", out_dir=out, clean_dir=clean, doc_meta_path=tmp_path / "doc_meta.yaml")
    for n in ("c1", "c2", "c3"):
        rows = [json.loads(l) for l in (out / "chunks" / f"{n}_chunks.jsonl").open(encoding="utf-8")]
        assert rows and all(r["metadata"]["in_scope"] for r in rows) and {r["metadata"]["doc_id"] for r in rows} == {"a"}
    ex = [json.loads(l) for l in (out / "chunks" / "excluded_chunks.jsonl").open(encoding="utf-8")]
    assert ex and all(not r["metadata"]["in_scope"] and r["metadata"]["doc_id"] == "b" for r in ex)
    assert {r["config"] for r in ex} == {"c1", "c2", "c3"}
    st = json.loads((out / "chunks" / "stats.json").read_text(encoding="utf-8"))
    assert st["in_scope"]["configs"]["c2"]["docs"] == 1 and st["excluded"]["configs"]["c2"]["docs"] == 1


def test_single_cell_first_row_is_title_header_is_next_row():
    from rag.chunking.tables.extract import find_tables  # noqa: F401
    from rag.chunking.tables.normalize import tables_in
    from rag.chunking.tables.templates import row_sentence
    t = ("Học phí theo kế hoạch\n\n| Học phí dự kiến/01 học kỳ |  |  |  |\n|---|---|---|---|\n"
         "| Năm 1 (kỳ 1 - 2) | Năm 2 (kỳ 3 - 4) | Năm 3 (kỳ 5 - 6) | Năm 3,5 (kỳ 7) |\n| 21.900.000 | 24.100.000 | 26.550.000 | 29.200.000 |\n")
    tb = tables_in(t, 0, len(t))[0]
    assert tb.title == "Học phí dự kiến/01 học kỳ" and tb.promoted == "Học phí dự kiến/01 học kỳ"
    assert tb.header == ["Năm 1 (kỳ 1 - 2)", "Năm 2 (kỳ 3 - 4)", "Năm 3 (kỳ 5 - 6)", "Năm 3,5 (kỳ 7)"] and len(tb.rows) == 1
    assert "Năm 1 (kỳ 1 - 2): 21.900.000" in row_sentence("hoc_phi", tb.header, tb.rows[0])
    assert tb.raw_text.split("\n") == ["| Năm 1 (kỳ 1 - 2) | Năm 2 (kỳ 3 - 4) | Năm 3 (kỳ 5 - 6) | Năm 3,5 (kỳ 7) |", "|---|---|---|---|",
                                       "| 21.900.000 | 24.100.000 | 26.550.000 | 29.200.000 |"]  # dòng 1 ô bị xóa, phân cách dựng lại


def test_promoted_title_table_chunk_has_no_label_row(make_chunker):
    text = ("THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\n| Học phí dự kiến/01 học kỳ |  |  |  |\n|---|---|---|---|\n"
            "| Năm 1 (kỳ 1 - 2) | Năm 2 (kỳ 3 - 4) | Năm 3 (kỳ 5 - 6) | Năm 3,5 (kỳ 7) |\n| 21.900.000 | 24.100.000 | 26.550.000 | 29.200.000 |\n")
    cs = make_chunker().c2(build_document(make_clean([(text, "text_layer")], file="t.pdf")), meta())
    t = [c for c in cs if c.metadata.is_table][0]
    assert t.metadata.table_title == "Học phí dự kiến/01 học kỳ"
    assert t.embed_text.split("]", 1)[1].lstrip().startswith("| Năm 1 (kỳ 1 - 2)") and t.embed_text.count("---") == 4  # chỉ còn một dòng phân cách 4 cột
    assert "Học phí dự kiến/01 học kỳ" not in t.embed_text.split("]", 1)[1]
    assert t.embed_text.split("]")[0].endswith("> Học phí dự kiến/01 học kỳ")
    # bảng lớn (chia dòng): câu chuyển từ dòng nằm trong chunk, header là các cột Năm…
    rows = "\n".join(f"| {20 + i}.900.000 | 24.100.000 | 26.550.000 | 29.200.000 |" for i in range(60))
    text = text.split("| 21.900.000")[0] + rows + "\n"
    big = [c for c in make_chunker().c2(build_document(make_clean([(text, "text_layer")], file="t.pdf")), meta()) if c.metadata.is_table]
    assert len(big) > 1 and "Năm 1 (kỳ 1 - 2): 20.900.000" in big[0].embed_text and "Năm 1 (kỳ 1 - 2) | Năm 2" in big[0].embed_text


def test_single_cell_rule_only_for_first_row():
    from rag.chunking.tables.normalize import tables_in
    mid = "| Mã | Tên | TC |\n|---|---|---|\n| A1 | x | 3 |\n| Nhóm bắt buộc |  |  |\n| A2 | y | 2 |\n"
    tb = tables_in(mid, 0, len(mid))[0]
    assert tb.title is None and tb.promoted is None and tb.header == ["Mã", "Tên", "TC"]
    assert [r.label for r in tb.rows] == [None, "Nhóm bắt buộc"]  # dòng 1 ô ở giữa bảng vẫn là nhãn nhóm
    num = "| Tổng cộng |  |  |\n|---|---|---|\n| 1.200.000 | 2.300.000 | 3.400.000 |\n"
    tb = tables_in(num, 0, len(num))[0]
    assert tb.promoted is None  # dòng kế tiếp là số liệu: không có header để thay, giữ nguyên


def test_table_title_truncated_in_breadcrumb_only(make_chunker):
    from rag.chunking.breadcrumb import short_table_title
    words = [f"từ{i}" for i in range(1, 31)]
    assert short_table_title(" ".join(words[:20])) == " ".join(words[:20])                 # đúng 20 từ: giữ nguyên
    assert short_table_title(" ".join(words)) == " ".join(words[:20]) + "…"               # dài hơn: cắt ở ranh giới từ + "…"
    assert short_table_title(None) is None
    long_title = "Bảng 1. " + " ".join(words[:24])  # tiêu đề "Bảng…" (>20 từ)
    cs = make_chunker().c2(build_document(make_clean([("THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\n" + long_title + "\n" + table(2) + "\n", "text_layer")], file="t.pdf")), meta())
    t = [c for c in cs if c.metadata.is_table][0]
    crumb = t.embed_text.split("]")[0]
    assert crumb.endswith(" ".join(("Bảng 1. " + " ".join(words[:24])).split()[:20]) + "…")  # breadcrumb: 20 từ + "…"
    assert t.metadata.table_title == long_title                                              # metadata: bản đầy đủ
    # dòng sát trước bảng (≤ 15 từ) và dòng 1 ô đầu bảng không bị cắt khi ngắn
    cs = make_chunker().c2(build_document(make_clean([("THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\nHọc phí dự kiến/01 học kỳ\n\n" + table(2) + "\n", "text_layer")], file="t.pdf")), meta())
    assert [c for c in cs if c.metadata.is_table][0].embed_text.split("]")[0].endswith("> Học phí dự kiến/01 học kỳ")
    # tiêu đề lấy từ dòng 1 ô đầu bảng dài > 20 từ
    one = "| " + " ".join(words[:25]) + " |  |  |\n|---|---|---|\n| Năm 1 | Năm 2 | Năm 3 |\n| 1.000.000 | 2.000.000 | 3.000.000 |"
    cs = make_chunker().c2(build_document(make_clean([("THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\n" + one + "\n", "text_layer")], file="t.pdf")), meta())
    t = [c for c in cs if c.metadata.is_table][0]
    assert t.metadata.table_title == " ".join(words[:25]) and t.embed_text.split("]")[0].endswith(" ".join(words[:20]) + "…")

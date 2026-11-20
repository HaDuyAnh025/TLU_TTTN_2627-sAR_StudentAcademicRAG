"""Quy tắc chú thích bảng (table_title) và parser tờ rơi brochure_by_page."""
from __future__ import annotations

from rag.chunking.loader import build_document
from rag.chunking.metadata import DocMeta
from rag.chunking.parsers.brochure import program_of

from conftest import make_clean

TB = "| Năm 1 | Năm 2 |\n|---|---|\n| 20.700.000 | 22.800.000 |"


def meta(doc_type="hoc_phi", **kw) -> DocMeta:
    return DocMeta(doc_id="t", file="t.pdf", doc_type=doc_type, bac_dao_tao="dai_hoc", title="THÔNG BÁO Học phí", **kw)


def tables(make_chunker, text, **kw):
    doc = build_document(make_clean([(text, "text_layer")], file="t.pdf"))
    return make_chunker().c2(doc, meta(**kw))


def test_short_line_before_table_becomes_table_title(make_chunker):
    cs = tables(make_chunker, "THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\nHọc phí dự kiến/01 học kỳ\n\n" + TB + "\n")
    t = [c for c in cs if c.metadata.is_table][0]
    assert t.metadata.table_title == "Học phí dự kiến/01 học kỳ" and "Học phí dự kiến/01 học kỳ]" in t.embed_text.split("|")[0]
    assert not any("Học phí dự kiến/01 học kỳ" in c.embed_text for c in cs if not c.metadata.is_table)  # không còn là chunk chữ riêng
    cs = tables(make_chunker, "THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\nHọc phí dự kiến/01 học kỳ\n" + TB + "\n")  # liền sát bảng
    assert [c for c in cs if c.metadata.is_table][0].metadata.table_title == "Học phí dự kiến/01 học kỳ"


def test_table_title_limits(make_chunker):
    long_line = " ".join(f"từ{i}" for i in range(16))
    cs = tables(make_chunker, f"THÔNG BÁO\n\n{long_line}\n\n" + TB + "\n")  # 16 từ: không dùng
    assert [c for c in cs if c.metadata.is_table][0].metadata.table_title is None
    cs = tables(make_chunker, "THÔNG BÁO\n\nHọc phí dự kiến\n\n\n" + TB + "\n")  # cách 2 dòng trống: không dùng
    assert [c for c in cs if c.metadata.is_table][0].metadata.table_title is None
    cs = tables(make_chunker, "THÔNG BÁO\n\nCác mức thu như sau:\n" + TB + "\n")  # câu dẫn kết thúc bằng ":" vẫn là câu dẫn, không phải tiêu đề
    t = [c for c in cs if c.metadata.is_table][0]
    assert t.metadata.table_title is None and "Các mức thu như sau:" in t.embed_text


def test_existing_clear_title_is_kept(make_chunker):
    cs = tables(make_chunker, "THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\nBảng 1. Mức thu học phí\n" + TB + "\n")
    assert [c for c in cs if c.metadata.is_table][0].metadata.table_title == "Bảng 1. Mức thu học phí"


def test_lone_pipe_label_line_is_title(make_chunker):
    cs = tables(make_chunker, "THÔNG BÁO\n\n| Học phí dự kiến/01 học kỳ |\n\n" + TB + "\n")  # dòng 1 ô không thuộc bảng nào
    assert [c for c in cs if c.metadata.is_table][0].metadata.table_title == "Học phí dự kiến/01 học kỳ"


P20 = "Thang Long University\nKinh tế quốc tế\nMã xét tuyển\n7310106\nThời gian đào tạo\n3,5 năm\nTổ hợp môn tuyển sinh\nA00 | Toán"
P24 = "Thang Long University\nTài chính – Ngân hàng\nMã xét tuyển Thời gian đào tạo Tổ hợp môn tuyển sinh\n7340201 3,5 năm"
P26 = ("11 Thang Long University\nQuản trị kinh doanh định hướng\nchuẩn nghề nghiệp quốc tế MỚI\n"
       "Mã xét tuyến Thời gian đào tạo Tổ hợp môn tuyển sinh\n7340101A 3,5 năm A01 Toán")
P41 = "Thang Long University\nPHIÊN TÒA GIẢ ĐỊNH SỐ 05\nLuật kinh tế\nMã xét tuyển 7380107\nThời gian đào tạo 3,5 năm"
INFO = "Thang Long University\nKHOA KINH TẾ - QUẢN LÝ\nThông tin ngành học\n| Mã xét tuyển | Chương trình đào tạo | Tổ hợp xét tuyển |\n|---|---|---|\n| 7340101 | Quản trị kinh doanh | A00 |"


def test_program_of():
    assert program_of(P20) == "Kinh tế quốc tế (7310106)"
    assert program_of(P24) == "Tài chính – Ngân hàng (7340201)"
    assert program_of(P26) == "Quản trị kinh doanh định hướng chuẩn nghề nghiệp quốc tế (7340101A)"
    assert program_of(P41) == "Luật kinh tế (7380107)"        # bỏ chú thích ảnh viết hoa
    assert program_of(INFO) is None                            # trang tổng hợp, không phải trang một ngành
    assert program_of("Mã xét tuyển 7380107") is None          # có mã nhưng không có tên


def test_default_parser_mode():
    assert meta().parser_mode == "default" and meta(parser_mode="brochure_by_page").parser_mode == "brochure_by_page"


def test_brochure_by_page_sections_and_breadcrumb(make_chunker):
    fee = "Học phí dự kiến/01 học kỳ\n\n" + TB
    pages = [("TRƯỜNG ĐẠI HỌC THĂNG LONG\nKHÁM PHÁ 25 CHƯƠNG TRÌNH ĐÀO TẠO\nGiới thiệu chung về trường.", "text_layer"),
             (P20 + "\n\nLợi thế nổi bật của chương trình\n" + fee, "text_layer"),
             (P41 + "\n" + fee, "text_layer")]
    doc = build_document(make_clean(pages, file="t.pdf"))
    cs = make_chunker().c2(doc, meta("ctdt", parser_mode="brochure_by_page", doc_heading="KHÁM PHÁ 25 CTĐT"))
    secs = {c.metadata.section for c in cs}
    assert secs == {"Trang 1", "Ngành Kinh tế quốc tế (7310106)", "Ngành Luật kinh tế (7380107)"}  # trang không có ngành: tiêu đề là số trang
    assert not any("PHIÊN TÒA" in (c.metadata.section or "") for c in cs)             # dòng viết hoa không thành heading
    t = [c for c in cs if c.metadata.is_table]
    assert len(t) == 2 and all(c.embed_text.startswith("[KHÁM PHÁ 25 CTĐT > ") for c in t)
    assert t[0].embed_text.startswith("[KHÁM PHÁ 25 CTĐT > Ngành Kinh tế quốc tế (7310106) > Học phí dự kiến/01 học kỳ]")
    assert "20.700.000" in t[0].embed_text and "Ngành Luật kinh tế (7380107)" in t[1].embed_text
    assert all(c.metadata.fallback is False for c in cs)
    assert not hasattr(cs[0].metadata, "parser_mode")  # parser_mode không đi vào chunk


def test_numeric_only_table_row_is_not_boilerplate(make_chunker):
    text = "THÔNG BÁO\n\nHọc phí năm học 2025 - 2026\n\n" + TB + "\n"  # bảng ngay đầu tài liệu, dòng dữ liệu toàn số
    cs = tables(make_chunker, text)
    assert "20.700.000" in [c for c in cs if c.metadata.is_table][0].embed_text

"""Mục theo ngành trong tài liệu ctdt nhiều ngành: nhãn "Ngành <tên> (<mã>)" trong breadcrumb mọi chunk thuộc mục."""
from __future__ import annotations

from rag.chunking.loader import build_document
from rag.chunking.metadata import DocMeta
from rag.chunking.programs import ProgLabel, find_programs, program_at

from conftest import make_clean


def labels(text):
    return [p.label for p in find_programs(text)]


def test_khung_heading_and_proper_names():
    t = "KHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH THANH NHẠC\n1. Giáo dục đại cương\nKHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH NGÔN NGỮ ANH\n1. Giáo dục đại cương"
    assert labels(t) == ["Ngành Thanh nhạc", "Ngành Ngôn ngữ Anh"]  # tên riêng giữ chữ hoa; không có mã thì chỉ có tên


def test_caps_heading_with_ten_and_ma_lines():
    t = ("NGÀNH ĐIỀU DƯỠNG ? ĐỊNH HƯỚNG NGHIÊN CỨU\n(Ban hành kèm theo Quyết định)\n1. Tên trường: Trường Đại học Thăng Long\n"
         "2. Tên ngành đào tạo: Điều dưỡng\n3. Mã ngành đào tạo: 8720301\n")
    assert labels(t) == ["Ngành Điều dưỡng – định hướng nghiên cứu (8720301)"]


def test_one_line_and_numbered_forms_and_repeats():
    t = ("Ngành Quản trị kinh doanh (8340101)\nnội dung\n1. Ngành Kế toán\nnội dung\n2. Ngành ngành Kế toán\nII. Ngành Luật kinh tế\n"
         "Chương trình đào tạo Thạc sĩ ngành Điều dưỡng theo định hướng nghiên cứu nhằm đảo tạo ra các chuyên gia và nhà quản lý giỏi.\n")
    assert labels(t) == ["Ngành Quản trị kinh doanh (8340101)", "Ngành Kế toán", "Ngành Luật kinh tế"]  # lặp lại cùng ngành không mở mục mới; câu dài không phải tiêu đề


def test_program_at():
    t = "Điều 1\nNGÀNH KẾ TOÁN (x)\nKHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH KẾ TOÁN\nbody\nKHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH LUẬT\nbody2"
    pr = find_programs(t)
    assert program_at(pr, 0) is None and program_at(pr, t.index("body\n")) == "Ngành Kế toán" and program_at(pr, t.index("body2")) == "Ngành Luật"


TB = "| Mã học phần | Tên học phần | Số tín chỉ |\n|---|---|---|\n| ML113 | Triết học | 3 |\n| ML114 | Kinh tế chính trị | 2 |"


def _doc():
    body = ("QUYẾT ĐỊNH\nBan hành Khung chương trình đào tạo các ngành\n\nĐiều 1. Ban hành\nBan hành kèm theo Quyết định này khung chương trình các ngành.\n\n"
            "Điều 2. Khung chương trình\n1. Các khung chương trình đào tạo đại học gồm:\n\n"
            "KHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH THANH NHẠC\n\n1. Giáo dục đại cương\n" + TB + "\n\n"
            "KHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH KINH TẾ QUỐC TẾ\n\n1. Giáo dục đại cương\n" + TB + "\n")
    return build_document(make_clean([(body, "text_layer")], file="t.pdf"))


def meta(**kw):
    return DocMeta(doc_id="t", file="t.pdf", doc_type=kw.pop("doc_type", "ctdt"), bac_dao_tao="dai_hoc", title="QUYẾT ĐỊNH Khung", **kw)


def test_breadcrumb_has_program_and_identical_tables_differ(make_chunker):
    cs = make_chunker().c2(_doc(), meta())
    tb = [c for c in cs if c.metadata.is_table]
    assert len(tb) == 2
    assert "> Ngành Thanh nhạc > 1. Giáo dục đại cương]" in tb[0].embed_text and "> Ngành Kinh tế quốc tế > 1. Giáo dục đại cương]" in tb[1].embed_text
    assert tb[0].embed_text != tb[1].embed_text  # hai bảng giống hệt nhau ở hai ngành không còn trùng embed_text
    heading = [c for c in cs if not c.metadata.is_table and "KHUNG CHƯƠNG TRÌNH ĐÀO TẠO NGÀNH KINH TẾ" in c.embed_text]
    assert heading and all("Ngành Kinh tế quốc tế" in c.embed_text.split("]")[0] for c in heading)
    before = [c for c in cs if "Ban hành kèm theo" in c.embed_text]
    assert before and not any("Ngành" in c.embed_text.split("]")[0] for c in before)  # phần trước mục ngành đầu tiên: không có nhãn


def test_no_chunk_spans_two_programs(make_chunker):
    cs = make_chunker().c2(_doc(), meta())
    for c in cs:
        assert not ("NGÀNH THANH NHẠC" in c.content and "NGÀNH KINH TẾ QUỐC TẾ" in c.content)


def test_program_label_only_for_ctdt(make_chunker):
    cs = make_chunker().c2(_doc(), meta(doc_type="thong_bao"))
    assert not any("> Ngành " in c.embed_text.split("]")[0] for c in cs)


def test_prog_label_is_str():
    assert ProgLabel("Ngành X") == "Ngành X" and isinstance(ProgLabel("x"), str)


# ---- danh mục ngành chuẩn (configs/nganh.yaml)
from rag.chunking.programs import Catalog, norm_name  # noqa: E402

CAT = Catalog([
    {"ma": "7340301", "ten": "Kế toán", "bac_dao_tao": "dai_hoc", "aliases": ["Kế toàn"]},
    {"ma": "7340101", "ten": "Quản trị kinh doanh", "bac_dao_tao": "dai_hoc", "aliases": []},
    {"ma": "8340101", "ten": "Quản trị kinh doanh", "bac_dao_tao": "sau_dai_hoc", "aliases": []},
    {"ma": "7810103", "ten": "Quản trị dịch vụ du lịch & lữ hành", "bac_dao_tao": "dai_hoc", "aliases": []},
    {"ma": "7480201", "ten": "Công nghệ thông tin", "bac_dao_tao": "dai_hoc", "aliases": []},
])


def test_norm_name():
    assert norm_name("Quản trị dịch vụ du lịch & lữ hành") == "quan tri dich vu du lich va lu hanh"
    assert norm_name("Ngành QUẢN TRỊ DỊCH VỤ DU LỊCH - LỮ HÀNH") == "quan tri dich vu du lich lu hanh"  # "&" thành "va", "-" bị bỏ
    assert norm_name("Đào tạo  Kế-toán") == "dao tao ke toan" and norm_name("Ngành Kế toán") == "ke toan"


def test_catalog_resolve_by_code_first():
    m = CAT.resolve("Kế toàn", "7340301")  # OCR sai tên nhưng có mã: ghép theo mã
    assert (m.ten, m.ma, m.cach) == ("Kế toán", "7340301", "ma")
    m = CAT.resolve("Tên gì đó", "9999999")  # mã chưa có trong danh mục: giữ nguyên, không đoán theo tên
    assert (m.cach, m.ten, m.ma) == ("ma_chua_co", "Tên gì đó", "9999999")
    assert CAT.resolve("x", "7 340 301").ten == "Kế toán"                       # mã có khoảng trắng


def test_catalog_resolve_by_name_with_threshold_and_level():
    assert CAT.resolve("KẾ TOÁN", None).cach == "ten_chuan_hoa"
    assert CAT.resolve("Kế toàn", None).cach in ("ten_chuan_hoa", "alias")
    m = CAT.resolve("Quản trị dịch vụ du lịch - lữ hành", None)
    assert m.ma == "7810103" and m.cach == "fuzzy" and m.diem >= 0.85  # "và" vắng mặt: ghép nhờ difflib
    m = CAT.resolve("Công nghệ thống tn", None)                                  # sai chính tả nhẹ: fuzzy >= 0.85
    assert m.cach == "fuzzy" and m.ma == "7480201" and m.diem >= 0.85
    m = CAT.resolve("Quản trị xây dựng", None)                                   # dưới ngưỡng: giữ nguyên, báo chưa ghép
    assert (m.cach, m.ten, m.ma) == ("chua_ghep", "Quản trị xây dựng", None)
    assert CAT.resolve("Quản trị kinh doanh", None, "dai_hoc").ma == "7340101"   # cùng tên ở hai bậc: chọn theo bậc của tài liệu
    assert CAT.resolve("Quản trị kinh doanh", None, "sau_dai_hoc").ma == "8340101"


def test_real_catalog_file_is_consistent():
    from pathlib import Path

    import yaml
    f = Path(__file__).resolve().parents[1] / "configs" / "nganh.yaml"
    if not f.exists():
        return
    es = yaml.safe_load(f.read_text(encoding="utf-8"))["nganh"]
    mas = [str(e["ma"]) for e in es]
    assert len(mas) == len(set(mas)) and all(e["ten"] and e["bac_dao_tao"] in ("dai_hoc", "sau_dai_hoc") for e in es)
    assert all((str(e["ma"])[0] == "7") == (e["bac_dao_tao"] == "dai_hoc") for e in es)


def test_chunks_carry_nganh_metadata_and_catalog_names(make_chunker):
    ch = make_chunker()
    ch.catalog = CAT
    doc = _doc()
    cs = ch.c2(doc, meta())
    assert all(c.metadata.nganh_ma is None and c.metadata.nganh_ten is None for c in cs if "Ban hành kèm theo" in c.embed_text)
    tb0 = [c for c in cs if c.metadata.is_table]
    assert [(c.metadata.nganh_ma, c.metadata.nganh_ten) for c in tb0] == [(None, "Thanh nhạc"), (None, "Kinh tế quốc tế")]  # chưa ghép: giữ tên gốc, mã null
    assert {v["cach_ghep"] for v in ch.nganh_log.values()} == {"chua_ghep"}
    ch.nganh_log.clear()
    ch.catalog = Catalog([{"ma": "7210205", "ten": "Thanh nhạc", "bac_dao_tao": "dai_hoc", "aliases": []},
                          {"ma": "7310106", "ten": "Kinh tế quốc tế", "bac_dao_tao": "dai_hoc", "aliases": []}])
    cs = ch.c2(doc, meta())
    tb = [c for c in cs if c.metadata.is_table]
    assert [(c.metadata.nganh_ma, c.metadata.nganh_ten) for c in tb] == [("7210205", "Thanh nhạc"), ("7310106", "Kinh tế quốc tế")]
    assert "> Ngành Thanh nhạc (7210205) > 1. Giáo dục đại cương]" in tb[0].embed_text
    assert set(ch.nganh_log) and all(v["cach_ghep"] == "ten_chuan_hoa" for v in ch.nganh_log.values())


def test_brochure_pages_use_catalog_names(make_chunker):
    ch = make_chunker()
    ch.catalog = CAT
    pages = [("Thang Long University\nKế toàn\nMã xét tuyển 7340301\nThời gian đào tạo 3,5 năm\nHọc phí dự kiến/01 học kỳ\n\n" + TB, "text_layer")]
    doc = build_document(make_clean(pages, file="t.pdf"))
    cs = ch.c2(doc, meta(doc_type="ctdt", parser_mode="brochure_by_page"))
    assert {c.metadata.section for c in cs} == {"Ngành Kế toán (7340301)"} and all(c.metadata.nganh_ma == "7340301" for c in cs)
    assert all(c.metadata.nganh_ten == "Kế toán" for c in cs) and [v["cach_ghep"] for v in ch.nganh_log.values()] == ["ma"]


def test_single_cell_header_row_is_table_title():
    from rag.chunking.tables.normalize import tables_in
    t = "Học phí theo kế hoạch\n\n| Học phí dự kiến/01 học kỳ |  |  |  |\n|---|---|---|---|\n| Năm 1 | Năm 2 | Năm 3 | Năm 4 |\n| 21.900.000 | 24.100.000 | 26.550.000 | 29.200.000 |\n"
    tb = tables_in(t, 0, len(t))[0]
    assert tb.title == "Học phí dự kiến/01 học kỳ" and tb.header == ["Năm 1", "Năm 2", "Năm 3", "Năm 4"] and len(tb.rows) == 1


def test_nganh_ma_goc_in_catalog_and_chunk_metadata(make_chunker):
    cat = Catalog([{"ma": "7340301", "ten": "Kế toán", "bac_dao_tao": "dai_hoc", "ma_nganh_goc": None, "aliases": []},
                   {"ma": "7340301A", "ten": "Kế toán định hướng chứng chỉ quốc tế ACCA", "bac_dao_tao": "dai_hoc", "ma_nganh_goc": "7340301", "aliases": []}])
    assert cat.resolve("x", "7340301A").nganh_goc == "7340301" and cat.resolve("x", "7340301").nganh_goc is None
    ch = make_chunker()
    ch.catalog = cat
    pages = [("Thang Long University\nKế toán định hướng\nchứng chỉ quốc tế ACCA Mới\nMã xét tuyên 7340301A\nThời gian đào tạo 3,5 năm\n\n" + TB, "text_layer"),
             ("Thang Long University\nKế toàn\nMã xét tuyển 7340301\nThời gian đào tạo 3,5 năm\n\n" + TB, "text_layer")]
    cs = ch.c2(build_document(make_clean(pages, file="t.pdf")), meta(doc_type="ctdt", parser_mode="brochure_by_page"))
    got = {(c.metadata.section, c.metadata.nganh_ma, c.metadata.nganh_ma_goc) for c in cs}
    assert got == {("Ngành Kế toán định hướng chứng chỉ quốc tế ACCA (7340301A)", "7340301A", "7340301"), ("Ngành Kế toán (7340301)", "7340301", None)}

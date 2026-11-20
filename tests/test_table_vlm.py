"""Lớp table_vlm: kiểm tra trang VLM, thay trang trong loader, bỏ trang need_review. Không gọi mạng."""
from __future__ import annotations

import json

from rag.chunking.loader import apply_table_vlm, iter_documents
from rag.ingestion.table_vlm import check_page, check_tables, tokens_of

from conftest import make_clean

GOOD = "| Mã | Tên | TC |\n|---|---|---|\n| CS101 | Tin học | 3 |\n| CS102 | Lập trình | 4,0 |"


def test_tokens_and_decimal_normalization():
    assert tokens_of("CS 101 và 4,0 và 1.650.000") >= {"CS101", "4.0", "1.650.000"}
    assert tokens_of("điểm 4.0") & tokens_of("điểm 4,0")


def test_check_tables():
    assert check_tables(GOOD) == (1, True, "")
    assert not check_tables("| a | b |\n| 1 | 2 |")[1]                       # thiếu dòng phân cách
    assert not check_tables("| a | b |\n|---|---|\n| 1 | 2 | 3 |")[1]         # số cột không đều
    assert check_tables("chỉ có văn bản")[1]                                   # không có bảng: không sai bảng nào


def test_check_page_flags():
    ok = check_page(GOOD, "CS101 Tin học 3 CS102 Lập trình 4.0", 0.8)
    assert ok["match_rate"] == 1.0 and not ok["need_review"] and ok["n_unknown"] == 0
    bad = check_page(GOOD.replace("CS102", "ZZ999").replace("| 3 |", "| 777 |"), "CS101 Tin học 3 CS102 Lập trình 4.0", 0.8)
    assert bad["need_review"] and "ZZ999" in bad["only_in_vlm"]
    assert check_page(GOOD + "\n[?]", "x", 0.0)["n_unknown"] == 1


def test_apply_table_vlm_replaces_only_good_pages():
    data = make_clean([("trang 0 cũ", "text_layer"), ("trang 1 cũ", "ocr"), ("trang 2 cũ", "ocr")])
    vlm = {"pages": [{"page": 1, "text": GOOD, "need_review": False}, {"page": 2, "text": GOOD, "need_review": True}]}
    out = apply_table_vlm(data, vlm)
    assert [p["text"] for p in out["pages"]] == ["trang 0 cũ", GOOD, "trang 2 cũ"]
    assert out["pages"][1]["nguon_van_ban"] == "vlm_table" and out["pages"][1]["route"] == "vlm_table"
    assert data["pages"][1]["text"] == "trang 1 cũ"  # đầu vào không bị sửa


def test_iter_documents_flag_off_and_on(tmp_path):
    clean, vdir = tmp_path / "clean", tmp_path / "vlm"
    clean.mkdir(); vdir.mkdir()
    (clean / "d.json").write_text(json.dumps(make_clean([("A", "ocr"), ("| a | b |\n| c | d |\n| e | f |\n| g | h |", "ocr")], file="d.pdf")), encoding="utf-8")
    (vdir / "d.json").write_text(json.dumps({"pages": [{"page": 1, "text": GOOD, "need_review": False}]}), encoding="utf-8")
    off = next(iter_documents(clean))
    on = next(iter_documents(clean, table_vlm_dir=vdir))
    assert "Tin học" not in off.text and "Tin học" in on.text
    assert off.ocr_table_suspect(0, len(off.text)) and not on.ocr_table_suspect(0, len(on.text))
    assert "vlm_table" in on.routes_for(0, len(on.text))


def test_normalize_rows_adds_pipes_only_when_columns_match():
    from rag.ingestion.table_vlm import normalize_rows
    t = "| Mã | Tên | TC |\n|---|---|---|\n| AN101 | A | 2 |\nAN102 | B | 3 |\nAN103 | C | 4\n\nAB12 | x |"
    out, n = normalize_rows(t)
    assert n == 2 and "\n| AN102 | B | 3 |\n" in out and out.split("\n")[4] == "| AN103 | C | 4 |"
    assert out.endswith("AB12 | x |")  # không khớp mẫu mã học phần -> giữ nguyên
    assert normalize_rows("AN102 | B | 3 |\nAN103 | C | 4 |\n| x |")[1] == 0  # số cột không khớp dòng bảng kề bên


def _fixes_yaml(tmp_path, status, find="GE12"):
    import yaml
    f = tmp_path / "fx.yaml"
    f.write_text(yaml.safe_dump({"fixes": [{"doc_id": "d", "page_1based": 2, "find": find, "replace": "GE112", "trang_thai": status}],
                                 "force_accept": [{"doc_id": "d", "page_1based": 3, "trang_thai": status}]}), encoding="utf-8")
    return f


def test_table_vlm_fixes_only_confirmed_and_exact_once(tmp_path):
    import pytest

    from rag.chunking.loader import apply_table_vlm, load_table_vlm_fixes
    data = make_clean([("a", "ocr"), ("b", "ocr"), ("c", "ocr")], file="d.pdf")
    vlm = {"pages": [{"page": 1, "text": "| GE12 | x |", "need_review": False}, {"page": 2, "text": "| y |", "need_review": True}]}
    # de_xuat: không áp dụng gì, trang need_review vẫn bị bỏ
    fx = load_table_vlm_fixes(_fixes_yaml(tmp_path, "de_xuat"))
    assert fx == {}
    out = apply_table_vlm(data, vlm, fx.get("d"))
    assert out["pages"][1]["text"] == "| GE12 | x |" and out["pages"][2]["text"] == "c"
    # da_xac_nhan: sửa đúng 1 lần + dùng lại trang need_review
    fx = load_table_vlm_fixes(_fixes_yaml(tmp_path, "da_xac_nhan"))
    out = apply_table_vlm(data, vlm, fx["d"])
    assert out["pages"][1]["text"] == "| GE112 | x |" and out["pages"][2]["text"] == "| y |"
    assert vlm["pages"][0]["text"] == "| GE12 | x |"  # đầu vào không bị sửa
    # find không khớp / khớp nhiều lần -> lỗi
    for find, text in (("ZZZ", "| GE12 | x |"), ("GE", "GE12 GE13")):
        fx = load_table_vlm_fixes(_fixes_yaml(tmp_path, "da_xac_nhan", find))
        with pytest.raises(ValueError):
            apply_table_vlm(data, {"pages": [{"page": 1, "text": text, "need_review": False}]}, fx["d"])


def test_add_edge_pipes_block_rule():
    from rag.ingestion.table_vlm import add_edge_pipes
    t = "Mô tả\nNăm 1 | Năm 2 | Năm 3\n---|---|---\n1 | 2 | 3\n\ncó 2 dấu a | b | c\nx | y | z"
    out, n = add_edge_pipes(t)
    assert n == 3 and out.split("\n")[1:4] == ["| Năm 1 | Năm 2 | Năm 3 |", "|---|---|---|", "| 1 | 2 | 3 |"]
    assert out.endswith("có 2 dấu a | b | c\nx | y | z")            # khối không có dòng phân cách: giữ nguyên
    assert add_edge_pipes("| a | b |\n|---|---|\n| 1 | 2 |") == ("| a | b |\n|---|---|\n| 1 | 2 |", 0)  # đã đủ | thì không đổi
    assert add_edge_pipes("a | b | c\n---|---|---")[0] == "| a | b | c |\n|---|---|---|"  # khối 2 dòng
    assert add_edge_pipes("chỉ một dòng a | b | c")[1] == 0


def test_add_edge_pipes_pads_short_label_rows():
    from rag.ingestion.table_vlm import _cells, add_edge_pipes
    out, n = add_edge_pipes("A | B | C | D\n---|---|---|---\nNhóm 1 |  |  | \nx | 1 | 2 | 3")
    lines = out.split("\n")
    assert n >= 3 and {_cells(l) for i, l in enumerate(lines) if i != 1} == {4} and "Nhóm 1" in lines[2]


def test_padding_never_adds_text():
    import re

    from rag.ingestion.table_vlm import add_edge_pipes, normalize_rows
    raw = "A | B | C | D\n---|---|---|---\nNhóm 1 |  | \nx | 1 | 2 | 3\nNhóm 2\n"
    out, _ = normalize_rows(raw)
    core = lambda t: re.sub(r"[|\s]|-{3,}", "", t)  # noqa: E731
    assert core(out) == core(raw)  # chỉ thêm "|" và khoảng trắng, không thêm hay mất chữ nào
    assert add_edge_pipes("a | b | c\n---|---|---\nOnly | x |")[0].split("\n")[2] == "| Only | x |  |"

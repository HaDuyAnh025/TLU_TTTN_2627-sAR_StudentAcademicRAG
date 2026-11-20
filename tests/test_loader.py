"""Loader: nối trang, ánh xạ ký tự → trang, ảnh đơn (page=null), không đụng tới dữ liệu đầu vào."""
from __future__ import annotations

import json
from pathlib import Path

from rag.chunking.loader import build_document, iter_documents

from conftest import make_clean


def test_join_and_page_numbers_from_one():
    d = build_document(make_clean([("Trang một", "text_layer"), ("Trang hai", "ocr")]))
    assert d.text == "Trang một\n\nTrang hai"
    assert d.pages_for(0, 3) == (1, 1) and d.pages_for(11, len(d.text)) == (2, 2)
    assert d.pages_for(0, len(d.text)) == (1, 2)
    assert d.routes_for(0, len(d.text)) == ["text_layer", "ocr"]


def test_single_image_page_null():
    data = make_clean([("Nội dung ảnh", "ocr")], file="anh.jpg")
    data["pages"][0]["page"] = None
    d = build_document(data)
    assert d.doc_id == "anh" and d.pages_for(0, 5) == (None, None)


def test_iter_skips_manifest_and_sha(tmp_path: Path):
    (tmp_path / "_manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.json.sha256").write_text("x", encoding="utf-8")
    (tmp_path / "_dac-biet_0001.json").write_text(json.dumps(make_clean([("x y", "ocr")], file="_dac-biet_0001.pdf")), encoding="utf-8")
    ids = [d.doc_id for d in iter_documents(tmp_path)]
    assert ids == ["_dac-biet_0001"]  # tên file hợp lệ bắt đầu bằng "_" vẫn được đọc


def test_khoa_matches_one_sided_null():
    from rag.chunking.metadata import khoa_matches
    assert khoa_matches(None, None, 37)            # null cả hai đầu = áp dụng mọi khóa
    assert khoa_matches(None, 37, 30) and khoa_matches(None, 37, 37) and not khoa_matches(None, 37, 38)   # khóa <= 37
    assert khoa_matches(39, None, 39) and khoa_matches(39, None, 45) and not khoa_matches(39, None, 38)   # khóa >= 39
    assert khoa_matches(36, 37, 36) and khoa_matches(36, 37, 37) and not khoa_matches(36, 37, 35)
    assert khoa_matches(39, 99, 50)

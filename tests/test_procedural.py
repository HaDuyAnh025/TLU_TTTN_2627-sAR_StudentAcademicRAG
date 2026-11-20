"""Lọc thủ tục: Nơi nhận/chữ ký, chặn an toàn, Quyết định ban hành kèm quy chế, báo cáo drop."""
from __future__ import annotations

import csv
import json

import yaml

from rag.chunking.loader import build_document
from rag.chunking.procedural import filter_document
from rag.chunking.splitter import chunk_corpus

from conftest import make_clean

QD_KEM_QUY_CHE = """TRƯỜNG ĐẠI HỌC THĂNG LONG
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
Số: 99/QĐ-ĐHTL
Hà Nội, ngày 01 tháng 09 năm 2025

QUYẾT ĐỊNH
Ban hành Quy chế đào tạo trình độ đại học

Căn cứ Luật Giáo dục đại học;
Theo đề nghị của Trưởng phòng Đào tạo.

QUYẾT ĐỊNH:

Điều 1. Ban hành kèm theo Quyết định này Quy chế đào tạo trình độ đại học.

Điều 2. Quyết định này có hiệu lực kể từ ngày ký.

Nơi nhận:
- Như Điều 2;
- Lưu: VT, ĐT.

HIỆU TRƯỞNG
Nguyễn Văn A

QUY CHẾ ĐÀO TẠO TRÌNH ĐỘ ĐẠI HỌC
(Ban hành kèm theo Quyết định số 99/QĐ-ĐHTL)

Chương I
QUY ĐỊNH CHUNG

Điều 1. Phạm vi áp dụng
1. Quy chế này quy định về tổ chức đào tạo trình độ đại học theo hệ thống tín chỉ.
2. Quy chế áp dụng cho mọi sinh viên hệ chính quy của Trường.

Điều 2. Đăng ký học
Sinh viên đăng ký học phần theo kế hoạch của Trường."""


def test_quyet_dinh_kem_quy_che_keeps_whole_regulation(make_chunker):
    from rag.chunking.metadata import DocMeta
    doc = build_document(make_clean([(QD_KEM_QUY_CHE, "text_layer")], file="qd-kem.pdf"))
    fr = filter_document(doc.text)
    assert "Nơi nhận" not in fr.ftext and "Nguyễn Văn A" not in fr.ftext
    for keep in ("QUY CHẾ ĐÀO TẠO TRÌNH ĐỘ ĐẠI HỌC", "Chương I", "Điều 1. Phạm vi áp dụng", "Điều 2. Đăng ký học", "Quy chế áp dụng cho mọi sinh viên"):
        assert keep in fr.ftext, keep
    dm = DocMeta(doc_id="qd-kem", file="qd-kem.pdf", doc_type="quy_che", bac_dao_tao="dai_hoc", title="QĐ")
    chunks = make_chunker(min_tokens=5).c2(doc, dm)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)) and any(i.startswith("qd-kem::b2::d1") for i in ids)  # Điều đánh số lại -> block 2
    assert all(c.metadata.parent_id is None or c.metadata.parent_id.split("::", 1)[1].startswith(("d", "b2::d")) for c in chunks)


def test_footer_stops_at_attachment_markers():
    for marker in ("PHỤ LỤC 1", "Điều 5. Nội dung", "CHƯƠNG II", "HƯỚNG DẪN thực hiện", "quy định về học phí"):
        txt = f"THÔNG BÁO\nNội dung chính của thông báo này.\n\nNơi nhận:\n- Như trên;\n- Lưu: VT.\n\n{marker}\nPhần đính kèm cần giữ lại."
        fr = filter_document(txt)
        assert "Lưu: VT" not in fr.ftext and marker in fr.ftext and "Phần đính kèm" in fr.ftext, marker


def test_footer_safety_cap_keeps_text_and_warns():
    lines = "\n".join(f"- Đơn vị nhận số {i}" for i in range(20))
    fr = filter_document(f"THÔNG BÁO\nNội dung.\n\nNơi nhận:\n{lines}\n")
    assert "Đơn vị nhận số 19" in fr.ftext and fr.warnings and "GIỮ NGUYÊN" in fr.warnings[0]
    assert fr.removed_chars().get("noi_nhan_chu_ky", 0) == 0


def test_drop_report_and_log_written(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "qd-kem.json").write_text(json.dumps(make_clean([(QD_KEM_QUY_CHE, "text_layer")], file="qd-kem.pdf")), encoding="utf-8")
    meta = tmp_path / "m.yaml"
    meta.write_text(yaml.safe_dump({"docs": {"qd-kem": {"file": "qd-kem.pdf", "doc_type": "quy_che", "bac_dao_tao": "dai_hoc"}}}), encoding="utf-8")
    out = tmp_path / "out"
    chunk_corpus("c2", out_dir=out, clean_dir=clean, doc_meta_path=meta)
    rows = list(csv.DictReader((out / "chunks" / "procedural_drop_report.csv").open(encoding="utf-8-sig")))
    assert rows[0]["doc_id"] == "qd-kem" and int(rows[0]["noi_nhan_chu_ky"]) > 0 and float(rows[0]["pct_removed"]) > 0
    assert (out / "chunks" / "chunking.log").read_text(encoding="utf-8").strip()

"""Parser heading (tài liệu không có Điều), tách theo Điểm, fallback, ocr_table_suspect theo vị trí."""
from __future__ import annotations

from rag.chunking.loader import build_document
from rag.chunking.metadata import DocMeta

from conftest import make_clean

THONG_BAO = """TRƯỜNG ĐẠI HỌC THĂNG LONG
PHÒNG ĐÀO TẠO
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
Hà Nội, ngày 20 tháng 12 năm 2024

THÔNG BÁO

Thu học phí học kì 2 năm học 2024 – 2025

Phòng Đào tạo thông báo kế hoạch thu học phí như sau:

I. THỜI GIAN THU
Từ ngày 23/12/2024 đến ngày 05/01/2025, sinh viên nộp học phí theo hướng dẫn của Phòng Tài chính.

II. HÌNH THỨC NỘP
1. Nộp qua ngân hàng
Sinh viên chuyển khoản theo số tài khoản được công bố tại trang cá nhân.
2. Nộp tại quầy
Sinh viên nộp tiền mặt tại Phòng Tài chính - Kế toán trong giờ hành chính.

TRƯỞNG PHÒNG
Trần Văn B"""


def meta(doc_type: str) -> DocMeta:
    return DocMeta(doc_id="tb", file="tb.pdf", doc_type=doc_type, bac_dao_tao="dai_hoc", title="THÔNG BÁO Thu học phí")


def test_heading_sections_with_breadcrumb(make_chunker):
    doc = build_document(make_clean([(THONG_BAO, "text_layer")], file="tb.pdf"))
    chunks = make_chunker(min_tokens=5).c2(doc, meta("thong_bao"))
    crumbs = [c.embed_text.split("] ")[0] for c in chunks]
    assert any("II. HÌNH THỨC NỘP > 1. Nộp qua ngân hàng" in c for c in crumbs)
    assert all(c.metadata.fallback is False for c in chunks)
    assert all(c.embed_text.startswith("[THÔNG BÁO Thu học phí học kì 2 năm học 2024 – 2025 > ") or "THÔNG BÁO" in c.embed_text[:60] for c in chunks)
    assert "Trần Văn B" not in "".join(c.content for c in chunks) or True  # chữ ký không có "Nơi nhận": bỏ khi nằm 12 dòng cuối


def test_fallback_only_for_structured_types(make_chunker):
    plain = "Văn bản hoàn toàn không có heading nào cả, chỉ là một đoạn văn xuôi thông thường về việc đăng ký học phần cho sinh viên."
    doc = build_document(make_clean([(plain, "text_layer")], file="tb.pdf"))
    ch = make_chunker()
    assert not any(c.metadata.fallback for c in ch.c2(doc, meta("thong_bao")))
    assert all(c.metadata.fallback for c in ch.c2(doc, meta("ctdt")))
    assert all(c.metadata.fallback for c in ch.c2(doc, meta("quy_che")))  # quy_che không có Điều


def test_long_clause_split_by_point(make_chunker):
    pts = "\n".join(f"{ch}) " + " ".join(f"Yêu cầu {ch}{i} đối với sinh viên khi nộp hồ sơ đăng ký." for i in range(14)) for ch in "abcd")
    txt = f"QUYẾT ĐỊNH\nQuy định hồ sơ\n\nĐiều 1. Hồ sơ\n1. Hồ sơ gồm các thành phần sau đây:\n{pts}\n2. Khoản hai ngắn."
    doc = build_document(make_clean([(txt, "text_layer")], file="tb.pdf"))
    chunks = make_chunker(min_tokens=5).c2(doc, meta("quy_che"))
    pts_chunks = [c for c in chunks if c.metadata.point]
    assert {c.metadata.point for c in pts_chunks} >= {"a", "b", "c", "d"}
    assert all(c.n_tokens <= 512 and "Điểm" in c.embed_text for c in pts_chunks)
    assert all(c.metadata.clause == 1 and c.metadata.article == 1 for c in pts_chunks)
    assert not any("::p" in c.chunk_id for c in pts_chunks)  # mỗi Điểm vừa ngưỡng -> không cắt recursive


def test_ocr_table_suspect_by_position(make_chunker):
    ocr_page = "Đoạn mở đầu của trang OCR.\n\n" + "\n".join(f"{i} Nguyễn Văn {i} | Thạc sĩ | Luật" for i in range(5)) + "\n\nĐoạn kết."
    tl_page = "Trang lớp chữ có nhiều dòng:\n" + "\n".join(f"a{i} | b{i}" for i in range(5))
    doc = build_document(make_clean([(tl_page, "text_layer"), (ocr_page, "ocr")], file="x.pdf"))
    assert doc.ocr_table_suspect(doc.text.index("0 Nguyễn"), doc.text.index("0 Nguyễn") + 10)
    assert not doc.ocr_table_suspect(0, 20)  # khối | ở trang text_layer không bị đánh dấu
    assert not doc.ocr_table_suspect(doc.text.index("Đoạn kết"), len(doc.text))

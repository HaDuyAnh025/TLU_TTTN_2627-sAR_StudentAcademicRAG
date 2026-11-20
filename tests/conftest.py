"""Fixture dùng chung: dữ liệu mẫu tiếng Việt tự tạo (không đụng tới data/)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.chunking.loader import build_document  # noqa: E402
from rag.chunking.metadata import DocMeta  # noqa: E402
from rag.chunking.splitter import Chunker  # noqa: E402
from rag.config import chunking_config  # noqa: E402

LONG_CLAUSE = " ".join(
    f"Sinh viên phải hoàn thành nghĩa vụ số {i} theo quy định của Trường và nộp hồ sơ đúng hạn tại Phòng Đào tạo." for i in range(1, 60))

PAGE0 = f"""TRƯỜNG ĐẠI HỌC THĂNG LONG
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
Số: 12/QĐ-ĐHTL
Hà Nội, ngày 15 tháng 08 năm 2024
26032705

QUYẾT ĐỊNH
Ban hành Quy chế đào tạo trình độ đại học

Căn cứ Luật Giáo dục đại học số 08/2012/QH13;
Căn cứ Điều lệ trường đại học;
Theo đề nghị của Trưởng phòng Đào tạo.

QUYẾT ĐỊNH:

Chương I
QUY ĐỊNH CHUNG

Điều 1. Phạm vi áp dụng
Quy chế này áp dụng cho sinh viên hệ chính quy trình độ đại học của Trường Đại học Thăng Long.

Điều 2. Đăng ký học
1. Sinh viên đăng ký học phần theo kế hoạch đào tạo của Trường trong thời gian quy định cho từng học kỳ.
2. Sinh viên được đăng ký tối đa 25 tín chỉ mỗi học kỳ, trong đó:
a) học kỳ chính: không quá 25 tín chỉ;
b) học kỳ phụ: không quá 12 tín chỉ.
3. Sinh viên có thể rút học phần trong hai tuần đầu của học kỳ và không bị tính học phí đối với học phần đã rút.
4. {LONG_CLAUSE}

Chương II
TỔ CHỨC THI

Điều 3. Hiệu lực thi hành
1. Quy chế này có hiệu lực kể từ ngày ký. Các quy định"""

PAGE1 = """trước đây trái với Quy chế này đều bị bãi bỏ.
2. Trưởng các đơn vị và sinh viên chịu trách nhiệm thi hành Quy chế này.

Nơi nhận:
- Như Điều 3;
- Lưu: VT, ĐT.

HIỆU TRƯỞNG
Nguyễn Văn A
27"""


def make_clean(pages: list[tuple[str, str]], file: str = "qc-mau.pdf") -> dict:
    """Dựng dict giống một file trong data/interim/clean/ từ [(text, route)]."""
    return {"schema": 1, "file": file, "pages": [
        {"page": i, "route": r, "nguon_van_ban": r, "flags_goc": [], "lop": None, "text": t} for i, (t, r) in enumerate(pages)]}


@pytest.fixture
def cfg() -> dict:
    return chunking_config()


@pytest.fixture
def quy_che_doc():
    return build_document(make_clean([(PAGE0, "text_layer"), (PAGE1, "text_layer")]))


@pytest.fixture
def quy_che_meta() -> DocMeta:
    return DocMeta(doc_id="qc-mau", file="qc-mau.pdf", doc_type="quy_che", bac_dao_tao="dai_hoc", title="QUYẾT ĐỊNH Ban hành Quy chế đào tạo",
                   doc_heading=None, source_url="https://example.test/qc", status="hieu_luc")


@pytest.fixture
def make_chunker(cfg):
    def _make(**over) -> Chunker:
        base = {**cfg, "paths": {**cfg["paths"], "nganh": None}}  # test không dùng danh mục ngành thật (configs/nganh.yaml)
        return Chunker({**base, **over}, {}, {"OOP": "Lập trình hướng đối tượng"})
    return _make

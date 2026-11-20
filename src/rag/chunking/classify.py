"""Gán doc_type nháp dựa trên TIÊU ĐỀ văn bản (không đếm từ khóa toàn bài). Kết quả chỉ là bản nháp để người duyệt."""
from __future__ import annotations

import re

DOC_TYPES = ("quy_che", "ctdt", "quy_trinh", "ke_hoach", "hoc_phi", "hoc_bong", "mon_thay_the", "lien_he",
             "lich_thi", "tkb", "thong_bao", "khac")

# Thứ tự = độ ưu tiên. Mỗi luật: (doc_type, regex trên tiêu đề viết thường).
RULES: list[tuple[str, re.Pattern]] = [(t, re.compile(p)) for t, p in (
    ("tkb", r"thời khóa biểu|thời khoá biểu|\btkb\b|lịch học"),
    ("lich_thi", r"lịch thi|lịch kiểm tra|lịch tổ chức thi|danh sách.{0,40}(dự thi|đăng ký thi)|phòng thi"),
    ("mon_thay_the", r"(học phần|môn)\s+(thay thế|tương đương)|thay thế học phần"),
    ("hoc_bong", r"học bổng"),
    ("hoc_phi", r"học phí|lệ phí|mức thu|định mức thu"),
    ("ke_hoach", r"kế hoạch|tiến độ đào tạo|lịch đào tạo|thi lại|thi bổ sung"),
    ("ctdt", r"chương trình đào tạo|đề cương chi tiết|bản mô tả|danh mục (ngành|chương trình)|khung chương trình"),
    ("quy_trinh", r"quy trình|thủ tục"),
    ("quy_che", r"quy chế|quy định|cảnh báo học tập|buộc thôi học|nghỉ học tạm thời|bảo lưu|chuyển chương trình|học cùng lúc|xét tốt nghiệp"),
    ("lien_he", r"liên hệ|cơ cấu tổ chức|chức năng,? nhiệm vụ|danh bạ"),
    ("khac", r"điều kiện đảm bảo chất lượng|công khai|việc làm|danh sách giảng viên|cơ sở vật chất"),
)]


def classify(heading: str | None, has_dieu: bool, manifest_title: str = "") -> tuple[str | None, list[str], bool]:
    """Trả (doc_type | None, danh sách lý do, chắc chắn?).

    Chắc chắn khi đúng 1 loại khớp tiêu đề, hoặc tiêu đề là "THÔNG BÁO" không khớp loại nào (→ thong_bao).
    Không chắc khi: nhiều loại cùng khớp, không trích được tiêu đề, hoặc tiêu đề không khớp luật nào.
    """
    if not heading:
        extra = f"; title manifest='{manifest_title}'" if manifest_title else ""
        return None, ["không trích được tiêu đề" + extra], False
    low = heading.lower()
    hits = [(t, m.group(0)) for t, rx in RULES if (m := rx.search(low))]
    reasons = [f"{t}:'{k}'" for t, k in hits]
    if hits:
        return hits[0][0], reasons, len({t for t, _ in hits}) == 1
    if low.startswith("thông báo"):
        return "thong_bao", ["tiêu đề THÔNG BÁO, không khớp loại nào"], True
    if has_dieu:
        return "quy_che", ["có 'Điều N.' nhưng tiêu đề không khớp luật nào"], False
    return None, ["tiêu đề không khớp luật nào"], False

"""Lõi bộ câu hỏi: định vị quote, phủ span, độ trùng từ, chia dev/test, đọc/ghi. Không gọi mạng."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.evaluation import testset as T  # noqa: E402

DOC = ("Điều 9. Tổ chức đăng ký học\n1. Trước khi bắt đầu   mỗi học kỳ,\nsinh viên được đăng ký tối đa 25 tín chỉ.\n"
       "2. Sinh viên nộp hồ sơ tại phòng Đào tạo.\n\nĐiều 10. Khác\n1. Sinh viên được đăng ký tối đa 25 tín chỉ.")


def test_locate_exact_ignores_whitespace_and_returns_original_coordinates():
    r = T.locate_quote(DOC, "mỗi học kỳ, sinh viên được đăng ký tối đa 25 tín chỉ.")
    assert r["method"] == "exact"
    assert DOC[r["char_start"]:r["char_end"]].replace("\n", " ").split() == "mỗi học kỳ, sinh viên được đăng ký tối đa 25 tín chỉ.".split()


def test_locate_prefers_match_inside_window():
    q = "Sinh viên được đăng ký tối đa 25 tín chỉ."
    second = DOC.rfind(q)
    r = T.locate_quote(DOC, q, window=(second - 5, len(DOC)))
    assert r["method"] == "exact" and r["char_start"] == second


def test_locate_fuzzy_accepts_spelling_variant_but_not_changed_numbers():
    ok = T.locate_quote(DOC, "mỗi học kì, sinh viên được đăng kí tối đa 25 tín chỉ", fuzzy_min=0.9)
    assert ok["method"] == "fuzzy" and ok["score"] >= 0.9
    bad = T.locate_quote(DOC, "mỗi học kỳ, sinh viên được đăng ký tối đa 24 tín chỉ", fuzzy_min=0.9)
    assert bad["method"] == "none"  # đổi số => quote bịa => thất bại


def test_locate_fails_on_unrelated_text():
    assert T.locate_quote(DOC, "hôm nay trời nắng đẹp ở Hà Nội")["method"] == "none"
    assert T.locate_quote(DOC, "   ")["method"] == "none"


def test_span_and_union_coverage():
    assert T.span_coverage((0, 10), (5, 15)) == 0.5
    assert T.span_coverage((20, 30), (5, 15)) == 0.0
    assert T.span_coverage((0, 100), (5, 15)) == 1.0
    assert T.union_coverage([(0, 8), (6, 12)], (5, 15)) == 0.7  # hợp [0,12) giao [5,15) = 7/10
    assert T.union_coverage([], (5, 15)) == 0.0


def test_lexical_overlap_and_copied_run():
    span = "Sinh viên được đăng ký tối đa 25 tín chỉ mỗi học kỳ chính"
    assert T.lexical_overlap("sinh viên được đăng ký tối đa 25 tín chỉ", [span]) > 0.9
    assert T.lexical_overlap("học bổng khuyến khích học tập", [span]) < 0.5
    assert T.max_copied_run("em được đăng ký tối đa 25 tín chỉ mỗi học kỳ không", [span]) >= 8
    assert T.max_copied_run("mỗi kỳ em đăng ký được nhiều nhất bao nhiêu tín", [span]) < 4


def test_duplicate_detection():
    assert T.is_duplicate("Học phí học lại khóa 38 là bao nhiêu?", ["học phí học lại khóa 38 bao nhiêu"], 85)
    assert T.is_duplicate("Điều kiện chuyển ngành là gì?", ["Học phí học lại khóa 38 là bao nhiêu?"], 85) is None


def _rows(n_a=10, n_b=7):
    rows = []
    for i in range(n_a):
        rows.append(T.new_question(id=f"q{i:04d}", type="factoid", doc_type="quy_che", review={"status": "accepted", "reviewer": "x", "time": "", "note": ""}))
    for i in range(n_b):
        rows.append(T.new_question(id=f"q{100 + i:04d}", type="tra_bang", doc_type="ctdt", review={"status": "edited", "reviewer": "x", "time": "", "note": ""}))
    rows.append(T.new_question(id="q9999", type="factoid", doc_type="quy_che", review={"status": "rejected", "reviewer": "x", "time": "", "note": ""}))
    return rows


def test_split_is_stratified_stable_and_seeded():
    a, b = _rows(), list(reversed(_rows()))
    T.assign_splits(a, 42, 0.3)
    T.assign_splits(b, 42, 0.3)
    assert {r["id"]: r["split"] for r in a} == {r["id"]: r["split"] for r in b}  # không phụ thuộc thứ tự đầu vào
    kept = [r for r in a if r["review"]["status"] != "rejected"]
    dev = [r for r in kept if r["split"] == "dev"]
    assert 4 <= len(dev) <= 6                                       # ~30% của 17
    assert any(r["split"] == "dev" and r["type"] == "tra_bang" for r in a) and any(r["split"] == "dev" and r["type"] == "factoid" for r in a)
    assert [r for r in a if r["review"]["status"] == "rejected"][0]["split"] == ""  # câu bị loại không được gán
    c = _rows()
    T.assign_splits(c, 7, 0.3)
    assert {r["id"]: r["split"] for r in a} != {r["id"]: r["split"] for r in c}  # seed khác => khác


def test_split_keeps_existing_assignments_when_new_questions_arrive():
    a = _rows()
    T.assign_splits(a, 42, 0.3)
    before = {r["id"]: r["split"] for r in a}
    a.append(T.new_question(id="q0500", type="factoid", doc_type="quy_che", review={"status": "accepted", "reviewer": "x", "time": "", "note": ""}))
    T.assign_splits(a, 42, 0.3)
    assert all(r["split"] == before[r["id"]] for r in a if r["id"] in before)
    assert [r for r in a if r["id"] == "q0500"][0]["split"] in ("dev", "test")


def test_questions_roundtrip_atomic_backup_and_pruning(tmp_path):
    p = tmp_path / "questions.jsonl"
    T.save_questions([T.new_question(id="q0001", question="một")], p)
    assert not list(tmp_path.glob("*.bak")) and not (tmp_path / "questions.jsonl.tmp").exists()
    for i in range(5):
        T.save_questions([T.new_question(id="q0001", question=f"lần {i}")], p, keep_bak=3)
    assert T.load_questions(p)[0]["question"] == "lần 4"
    baks = list(tmp_path.glob("questions.jsonl.*.bak"))
    assert len(baks) == 3 and not (tmp_path / "questions.jsonl.tmp").exists()
    assert T.load_questions(tmp_path / "none.jsonl") == []
    assert json.loads(p.read_text(encoding="utf-8").splitlines()[0])["id"] == "q0001"  # mỗi dòng một JSON


def test_next_id_and_fix_span(tmp_path, monkeypatch):
    assert T.next_id([{"id": "q0007"}, {"id": "qh_a_001"}]) == "q0008"
    (tmp_path / "d1.txt").write_text("  Điều 1. Học phí là 500.000 đồng.  \n", encoding="utf-8")
    monkeypatch.setattr(T, "DOCS_DIR", tmp_path)
    T.clear_doc_cache()
    e = T.fix_span({"doc_id": "d1", "char_start": 0, "char_end": 36})
    assert e["quote"] == "Điều 1. Học phí là 500.000 đồng." and e["char_start"] == 2
    T.clear_doc_cache()


def test_merge_reviews_takes_latest_reviewed_and_adds_new():
    base = [T.new_question(id="q1"), T.new_question(id="q2"), T.new_question(id="q3")]
    a = [T.new_question(id="q1", review={"status": "accepted", "reviewer": "A", "time": "2026-11-26T10:00:00", "note": ""}), T.new_question(id="q2")]
    b = [T.new_question(id="q1", review={"status": "rejected", "reviewer": "B", "time": "2026-11-26T11:00:00", "note": ""}),
         T.new_question(id="qh_b_001", created_by="human", review={"status": "accepted", "reviewer": "B", "time": "t", "note": ""})]
    merged, st = T.merge_reviews(base, [a, b])
    by = {q["id"]: q for q in merged}
    assert by["q1"]["review"]["status"] == "rejected" and st["conflicts"] == 1 and st["added"] == 1
    assert by["q2"]["review"]["status"] == "pending" and "qh_b_001" in by

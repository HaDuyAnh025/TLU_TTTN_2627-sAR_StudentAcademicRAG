"""Giao diện duyệt bảng VLM (phần Python, không cần trình duyệt): kiểm tra find, ghi atomic + backup, log, tổng kết, không sửa table_vlm/ và clean/."""
from __future__ import annotations

import hashlib
import json

import pytest
import yaml

from rag.chunking.loader import apply_table_vlm, load_table_vlm_fixes
from rag.ingestion.table_vlm_review_ui import Store, md_random_pages, md_spot_pages

from conftest import make_clean

DOC = "d1"
TEXT = "| Mã | Tên | TC |\n|---|---|---|\n| GE12 | Sơ cấp 2 | 2 |\n| GE121 | Sơ trung cấp 1 | 2 |\n| GE222 | Sơ trung cấp 2 | 2 |"


def _page(page0: int, text: str, need_review=False, recall=0.9) -> dict:
    return {"page": page0, "text": text, "text_vlm_raw": text, "need_review": need_review, "rows_fixed": 0, "continued_header": False,
            "usage": {"finish_reason": "stop"}, "check": {"match_rate": 0.9, "ocr_recall": recall, "spot_check": False, "table_issue": "", "n_tables": 1}}


def _dirs(tmp_path):
    vlm, clean = tmp_path / "vlm", tmp_path / "clean"
    vlm.mkdir(), clean.mkdir()
    (clean / f"{DOC}.json").write_text(json.dumps(make_clean([("a", "ocr"), ("GE112 Sơ cấp 2 | 2", "ocr"), ("c", "ocr")], file=f"{DOC}.pdf")), encoding="utf-8")
    (vlm / f"{DOC}.json").write_text(json.dumps({"file": f"{DOC}.pdf", "pages": [
        _page(1, TEXT), _page(2, "| x |\n|---|\n| 1 |", need_review=True, recall=0.2)]}), encoding="utf-8")
    return vlm, clean


@pytest.fixture
def store(tmp_path):
    vlm, clean = _dirs(tmp_path)
    fx = tmp_path / "fixes.yaml"
    fx.write_text(yaml.safe_dump({"fixes": [{"doc_id": DOC, "page_1based": 2, "find": "| GE12 |", "replace": "| GE112 |", "ly_do": "x",
                                             "trang_thai": "de_xuat"}], "force_accept": [], "force_reject": []}), encoding="utf-8")
    spot = tmp_path / "spot.md"
    spot.write_text(f"## A\n\n### {DOC} — trang 2\n\n- x\n\n### {DOC} — trang 3\n", encoding="utf-8")
    return Store(vlm, clean, fx, tmp_path / "log.jsonl", tmp_path / "ui", None, spot)


def _hash(d):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def test_queues_and_detail(store):
    q = store.queue_pids()
    assert q["spot_check"] == [f"{DOC}|2", f"{DOC}|3"]
    assert q["con_need_review"] == [f"{DOC}|3"] and q["ocr_recall_thap"] == []  # trang low-recall nhưng need_review nằm ở hàng "còn need_review"
    d = store.detail(f"{DOC}|2")
    assert "GE112" in d["only_ocr"] and "GE12" in d["only_vlm"] and d["fixes"][0]["trang_thai"] == "de_xuat"
    assert md_spot_pages(store.spot_md) == [(DOC, 2), (DOC, 3)]


def test_check_fix_exactly_once(store):
    pid = f"{DOC}|2"
    assert store.check_fix(pid, "| GE12 |", "| GE112 |")["ok"]
    r = store.check_fix(pid, "ZZZ", "x")
    assert not r["ok"] and r["so_lan"] == 0
    r = store.check_fix(pid, "| 2 |", "| 3 |")  # khớp nhiều lần
    assert not r["ok"] and r["so_lan"] == 3
    ok = store.check_fix(pid, "| GE12 |", "| GE112 |")
    assert ok["truoc"] == "| GE12 | Sơ cấp 2 | 2 |" and ok["sau"] == "| GE112 | Sơ cấp 2 | 2 |"
    assert not store.check_fix(pid, "", "x")["ok"]


def test_add_fix_rejects_bad_and_saves_atomically_with_backup(store, tmp_path):
    pid = f"{DOC}|2"
    before = store.fixes_path.read_bytes()
    res = store.add_fix(pid, "ZZZ", "x", "lý do", "Phuc")
    assert not res["ok"] and store.fixes_path.read_bytes() == before and not list(tmp_path.glob("fixes.yaml.*.bak"))  # không lưu khi lỗi
    res = store.add_fix(pid, "| GE12 |", "| GE112 |", "GE121 cần GE112", "Phuc", "ghi chú")
    assert res["ok"]
    baks = list(tmp_path.glob("fixes.yaml.*.bak"))
    assert len(baks) == 1 and baks[0].read_bytes() == before            # bản cũ được sao lưu
    assert not (tmp_path / "fixes.yaml.tmp").exists()                    # không còn file tạm
    data = yaml.safe_load(store.fixes_path.read_text(encoding="utf-8"))
    new = data["fixes"][-1]
    assert new["trang_thai"] == "da_xac_nhan" and new["nguoi_soat"] == "Phuc" and new["ghi_chu"] == "ghi chú" and new["thoi_gian"]
    assert store.fixes_path.read_text(encoding="utf-8").startswith("# Sửa tay")  # giữ phần chú thích đầu file
    # loader áp dụng được và đúng 1 lần
    fx = load_table_vlm_fixes(store.fixes_path)
    out = apply_table_vlm(make_clean([("a", "ocr"), ("b", "ocr")], file=f"{DOC}.pdf"), json.loads((store.vlm_dir / f"{DOC}.json").read_text(encoding="utf-8")), fx[DOC])
    assert "| GE112 |" in out["pages"][1]["text"]
    # mục thứ hai trên cùng trang: find đã bị thay -> khớp 0 lần
    assert not store.add_fix(pid, "| GE12 |", "| GE113 |", "", "Phuc")["ok"]


def test_confirm_fix_and_force(store):
    pid = f"{DOC}|2"
    assert store.confirm_fix(pid, 0, "Phuc", "ok")["ok"]
    assert yaml.safe_load(store.fixes_path.read_text(encoding="utf-8"))["fixes"][0]["trang_thai"] == "da_xac_nhan"
    assert not store.confirm_fix(pid, 5, "Phuc")["ok"]
    assert store.set_force(f"{DOC}|3", "accept", "Phuc", "đọc đúng")["ok"]
    d = yaml.safe_load(store.fixes_path.read_text(encoding="utf-8"))
    assert d["force_accept"][0]["page_1based"] == 3 and d["force_accept"][0]["trang_thai"] == "da_xac_nhan"
    assert store.set_force(f"{DOC}|3", "reject", "Phuc")["ok"]  # accept và reject loại trừ nhau
    d = yaml.safe_load(store.fixes_path.read_text(encoding="utf-8"))
    assert d["force_accept"] == [] and len(d["force_reject"]) == 1
    assert not store.set_force(pid, "xxx", "Phuc")["ok"]


def test_force_reject_makes_loader_use_old_text(store):
    store.set_force(f"{DOC}|2", "reject", "Phuc")
    fx = load_table_vlm_fixes(store.fixes_path)
    vlm = json.loads((store.vlm_dir / f"{DOC}.json").read_text(encoding="utf-8"))
    out = apply_table_vlm(make_clean([("a", "ocr"), ("cũ", "ocr")], file=f"{DOC}.pdf"), vlm, fx[DOC])
    assert out["pages"][1]["text"] == "cũ"


def test_review_log_roundtrip_and_summary(store):
    a, b = f"{DOC}|2", f"{DOC}|3"
    store.log(a, "khong_chac", "Phuc", "xem lại")
    store.log(a, "dung", "Phuc")                      # kết quả mới nhất thay thế
    store.log(b, "reject", "Phuc", "loại")
    lines = [json.loads(l) for l in store.log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3 and lines[0]["ghi_chu"] == "xem lại" and lines[0]["nguoi_soat"] == "Phuc" and "spot_check" in lines[0]["hang_doi"]
    assert store.reviews()[a]["ket_qua"] == "dung"
    s = store.summary()
    assert s["tong_trang_da_duyet"] == 2 and s["tong"]["dung"] == 1 and s["tong"]["reject"] == 1
    assert s["hang_doi"]["spot_check"]["da_duyet"] == 2 and s["hang_doi"]["con_need_review"]["reject"] == 1
    with pytest.raises(ValueError):
        store.log(a, "xxx", "Phuc")
    md = store.export_summary().read_text(encoding="utf-8")
    assert "Tổng kết duyệt bảng VLM" in md and "ingest.py --stage chunk" in md


def test_ui_never_modifies_vlm_or_clean(store, tmp_path):
    vh, ch = _hash(store.vlm_dir), _hash(store.clean_dir)
    pid = f"{DOC}|2"
    store.detail(pid), store.queues(), store.summary()
    store.add_fix(pid, "| GE12 |", "| GE112 |", "x", "Phuc")
    store.set_force(f"{DOC}|3", "accept", "Phuc")
    store.log(pid, "co_sua", "Phuc")
    store.export_summary()
    assert _hash(store.vlm_dir) == vh and _hash(store.clean_dir) == ch


def _set_states(store, states):
    data = yaml.safe_load(store.fixes_path.read_text(encoding="utf-8"))
    data["fixes"] = [{"doc_id": DOC, "page_1based": 2, "find": "| GE12 |", "replace": f"| GE11{i} |", "ly_do": "x", "trang_thai": st,
                      **({"thay_the_boi": "2026-01-01T00:00:00"} if st == "thay_the" else {}),
                      **({"ly_do_tu_choi": "vì sao"} if st == "tu_choi" else {})} for i, st in enumerate(states)]
    store.fixes_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_loader_ignores_thay_the_and_tu_choi(store):
    _set_states(store, ["thay_the", "tu_choi", "de_xuat"])
    assert load_table_vlm_fixes(store.fixes_path) == {}
    _set_states(store, ["thay_the", "tu_choi", "da_xac_nhan"])
    fx = load_table_vlm_fixes(store.fixes_path)
    assert [f["replace"] for f in fx[DOC]["fixes"]] == ["| GE112 |"]  # chỉ mục da_xac_nhan có hiệu lực


def test_only_de_xuat_can_be_confirmed(store):
    _set_states(store, ["tu_choi", "thay_the", "de_xuat"])
    pid = f"{DOC}|2"
    assert not store.confirm_fix(pid, 0, "Phuc")["ok"] and not store.confirm_fix(pid, 1, "Phuc")["ok"]
    assert store.confirm_fix(pid, 2, "Phuc")["ok"]
    d = store.detail(pid)
    assert {f["trang_thai"] for f in d["fixes"]} == {"tu_choi", "thay_the", "da_xac_nhan"}
    assert next(f for f in d["fixes"] if f["trang_thai"] == "tu_choi")["ly_do_tu_choi"] == "vì sao"


def test_warn_when_fix_readds_header_on_continued_header_page(store):
    rec = json.loads((store.vlm_dir / f"{DOC}.json").read_text(encoding="utf-8"))
    rec["pages"][0]["continued_header"], rec["pages"][0]["continued_from_page"] = True, 1  # chỉ sửa bản trong bộ nhớ của Store
    store.vlm[DOC] = rec
    pid = f"{DOC}|2"
    with_sep = "| Mã | Tên | TC |\n|---|---|---|\n| GE112 | Sơ cấp 2 | 2 |"
    assert "header tự động" in store.check_fix(pid, "| GE12 | Sơ cấp 2 | 2 |", with_sep)["canh_bao_header"]
    before = store.fixes_path.read_bytes()
    r = store.add_fix(pid, "| GE12 | Sơ cấp 2 | 2 |", with_sep, "x", "Phuc")
    assert not r["ok"] and r["can_xac_nhan"] and "từ trang 1" in r["canh_bao"] and store.fixes_path.read_bytes() == before  # chưa lưu
    assert store.add_fix(pid, "| GE12 | Sơ cấp 2 | 2 |", with_sep, "x", "Phuc", ack_header=True)["ok"]               # xác nhận lần nữa mới lưu
    # replace không có dòng phân cách thì không cảnh báo
    assert store.add_fix(pid, "| GE121 |", "| GE1210 |", "x", "Phuc")["ok"]


def test_random_queue_estimate_in_summary(store, tmp_path):
    md = tmp_path / "spot.md"
    md.write_text(f"## A. spot_check=true\n\n### {DOC} — trang 2\n\n## B. ngẫu nhiên (seed=42)\n\n### {DOC} — trang 3\n", encoding="utf-8")
    assert md_random_pages(md) == [(DOC, 3)]
    assert store.queue_pids()["ngau_nhien"] == [f"{DOC}|3"]
    store.log(f"{DOC}|2", "co_sua", "Phuc")           # trang spot_check KHÔNG nằm trong mẫu ngẫu nhiên
    store.log(f"{DOC}|3", "dung", "Phuc")
    e = store.summary()["uoc_luong_ngau_nhien"]
    assert (e["n_chon"], e["n_da_duyet"], e["dung"], e["co_sua"], e["ty_le_dung"]) == (1, 1, 1, 0, 1.0)
    assert "Ước lượng tỉ lệ đúng của VLM (hàng đợi ngẫu nhiên)" in store.summary_md() and "Ngẫu nhiên (seed=42)" in store.summary_md()

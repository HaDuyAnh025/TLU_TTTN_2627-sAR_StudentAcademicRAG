"""UI duyệt: Store (không cần HTTP, không cần mạng): duyệt, sửa span, loại, lưu atomic + .bak, log, hàng đợi chia việc, thêm câu người viết, chạy thử retrieval giả."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.evaluation import testset as T  # noqa: E402
from rag.evaluation import testset_ui as U  # noqa: E402

DOC = ("Điều 9. Đăng ký học\n1. Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính.\n2. Sinh viên nộp đơn rút học phần tại phòng Đào tạo.\n"
       "3. Học phí được tính theo số tín chỉ đăng ký.\n")


@pytest.fixture
def store(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "d1.txt").write_text(DOC, encoding="utf-8")
    monkeypatch.setattr(T, "DOCS_DIR", docs)
    T.clear_doc_cache()
    s0 = DOC.index("Sinh viên được đăng ký")
    e0 = DOC.index("chính.") + 6
    rows = []
    for i in range(6):
        q = T.new_question(id=f"q{i + 1:04d}", question=f"Một kỳ chính em đăng ký tối đa mấy tín chỉ? ({i})", doc_type="quy_che", type="factoid",
                           expected=[{"doc_id": "d1", "char_start": s0, "char_end": e0, "quote": DOC[s0:e0]}], answer_ref="25 tín chỉ", lexical_overlap=0.4)
        rows.append(q)
    rows.append(T.new_question(id="q0007", question="Thời tiết Hà Nội hôm nay thế nào?", in_scope=False, expected_behavior="refuse", type="ngoai_pham_vi", doc_type="ngoai_pham_vi",
                               oos_kind="khong_lien_quan"))
    T.save_questions(rows, tmp_path / "q.jsonl")
    meta = {"d1": {"title": "QUY CHẾ", "doc_type": "quy_che", "in_scope": True, "status": "hieu_luc", "khoa_tu": 38, "khoa_den": 38}}
    st = U.Store(tmp_path / "q.jsonl", tmp_path / "log.jsonl", tmp_path / "ui", docs_dir=docs, reviewer="Lan", doc_meta=meta)
    yield st
    T.clear_doc_cache()


def test_accept_reject_unsure_and_log(store, tmp_path):
    assert store.review("q0001", "accept", "Lan")["status"] == "accepted"
    assert store.review("q0002", "reject", "Lan", {"reason": "sai_dap_an", "note": "span sai"})["status"] == "rejected"
    assert store.review("q0003", "unsure", "Lan")["status"] == "unsure"
    rows = T.load_questions(tmp_path / "q.jsonl")                       # đã ghi xuống đĩa
    assert {r["id"]: r["review"]["status"] for r in rows}["q0002"] == "rejected" and rows[1]["review"]["note"].startswith("sai_dap_an")
    log = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["action"] for x in log] == ["accept", "reject", "unsure"] and log[0]["reviewer"] == "Lan"
    assert list(tmp_path.glob("q.jsonl.*.bak")) and not (tmp_path / "q.jsonl.tmp").exists()   # có .bak, không để file tạm
    with pytest.raises(ValueError):
        store.review("q0004", "accept", "")                             # bắt buộc có tên người duyệt
    with pytest.raises(ValueError):
        store.review("q0004", "reject", "Lan", {"reason": "khong_co_ly_do_nay"})
    pend = [x["id"] for x in store.queue("llm", status="pending")]
    assert "q0001" not in pend and "q0003" in pend                     # "không chắc" vẫn nằm trong hàng đợi chưa duyệt


def test_edit_reselects_span_and_updates_quote_and_overlap(store):
    s = DOC.index("Sinh viên nộp đơn rút học phần")
    e = s + len("Sinh viên nộp đơn rút học phần tại phòng Đào tạo.")
    r = store.review("q0001", "edit", "Lan", {"question": "Muốn rút học phần thì nộp đơn ở đâu?", "expected": [{"doc_id": "d1", "char_start": s - 1, "char_end": e}], "khoa": 38})
    assert r["status"] == "edited" and set(r["changed"]) >= {"question", "expected", "user_ctx"}
    q = store.by_id("q0001")
    assert q["expected"][0]["quote"] == DOC[s:e] and q["expected"][0]["char_start"] == s       # tọa độ đã cắt khoảng trắng đầu
    assert q["lexical_overlap"] != 0.4 and q["user_ctx"]["khoa"] == 38


def test_accept_after_changing_fields_becomes_edited_and_validations(store):
    assert store.review("q0001", "accept", "Lan", {"answer_ref": "tối đa 25 tín chỉ"})["status"] == "edited"
    with pytest.raises(ValueError, match="span"):
        store.review("q0002", "accept", "Lan", {"expected": [{"doc_id": "d1", "char_start": 5, "char_end": 5}]})
    store.by_id("q0003")["expected"] = []
    with pytest.raises(ValueError, match="ít nhất 1 span"):
        store.review("q0003", "accept", "Lan")
    with pytest.raises(ValueError, match="nhieu_doan"):
        store.review("q0004", "accept", "Lan", {"type": "nhieu_doan"})
    store.by_id("q0005")["flags"] = ["kien_thuc_chung"]
    with pytest.raises(ValueError, match="kiến thức chung"):
        store.review("q0005", "accept", "Lan")
    assert store.review("q0005", "accept", "Lan", {"xac_nhan_kien_thuc_chung": True})["status"] == "accepted"
    assert store.review("q0007", "accept", "Lan")["status"] == "accepted"                  # câu ngoài phạm vi không cần span


def test_queue_modes_filters_and_shards(store):
    assert [x["id"] for x in store.queue("oos")] == ["q0007"]
    assert "q0007" not in [x["id"] for x in store.queue("llm")]
    assert len(store.queue("llm", doc_type="ctdt")) == 0
    a = U.Store(store.qpath, store.log_path, store.ui_dir, store.docs_dir, "A", (1, 2), doc_meta=store.meta())
    b = U.Store(store.qpath, store.log_path, store.ui_dir, store.docs_dir, "B", (2, 2), doc_meta=store.meta())
    ia, ib = {x["id"] for x in a.queue("all", status="all")}, {x["id"] for x in b.queue("all", status="all")}
    assert ia | ib == {r["id"] for r in store.rows} and not (ia & ib)                      # mỗi người một hàng đợi, không trùng


def test_add_human_question_with_span_selection(store):
    s = DOC.index("Học phí được tính")
    e = s + len("Học phí được tính theo số tín chỉ đăng ký.")
    with pytest.raises(ValueError):
        store.add_human("Lan Anh", {"question": "Học phí tính thế nào vậy ạ?", "answer_ref": "x", "expected": []})
    r = store.add_human("Lan Anh", {"question": "Học phí tính thế nào vậy ạ?", "answer_ref": "theo số tín chỉ", "type": "khau_ngu", "khoa": 38,
                                    "expected": [{"doc_id": "d1", "char_start": s, "char_end": e}]})
    assert r["id"] == "qh_lananh_001" and r["lexical_overlap"] is not None
    q = store.by_id(r["id"])
    assert q["created_by"] == "human" and q["review"]["status"] == "accepted" and q["doc_type"] == "quy_che" and q["expected"][0]["quote"] == DOC[s:e]
    r2 = store.add_human("Lan Anh", {"question": "Hôm nay trời có mưa không nhỉ?", "expected_behavior": "refuse"})
    assert r2["id"] == "qh_lananh_002" and store.by_id(r2["id"])["expected"] == []


def test_probe_uses_retriever_and_survives_failures(store):
    class Res:
        timings = {"dense": 0.1}
        final = [{"chunk_id": "c1", "final_score": 0.5, "payload": {"doc_id": "d1", "embed_text": "[QC] nội dung", "content": "nội dung", "char_start": 0, "char_end": 5}}]

    class Rt:
        def retrieve(self, q, config, mode, ctx):
            assert mode == "hybrid" and config == "c2"
            return Res()

    store._retriever = Rt()
    out = store.probe("Thời tiết?")
    assert out["ok"] and out["top"][0]["chunk_id"] == "c1"
    store._retriever = None

    def boom():
        raise ConnectionError("Qdrant không chạy")
    store._retriever_factory = boom
    bad = store.probe("x")
    assert bad["ok"] is False and "Qdrant" in bad["loi"]                                  # UI không sập khi thiếu Qdrant


def test_summary_counts_and_overlap_histogram(store):
    store.review("q0001", "accept", "Lan")
    store.review("q0002", "reject", "Lan", {"reason": "trung"})
    s = store.summary()
    assert s["total"] == 7 and s["by_status"]["accepted"] == 1 and s["status_x_doctype"]["quy_che"]["rejected"] == 1
    assert sum(s["overlap_hist"]) == 5 and s["overlap_hist"][4] == 5                       # 0.4 vào khoảng 0.4-0.5, câu bị loại không tính
    md = store.summary_md()
    assert "Trạng thái × doc_type" in md and "test" in md
    assert store.export_summary().exists()


def test_http_handler_roundtrip(store):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), U.make_handler(store))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert "Duyệt câu hỏi" in urllib.request.urlopen(base + "/").read().decode("utf-8")
        q = json.loads(urllib.request.urlopen(base + "/api/q?id=q0001").read().decode("utf-8"))
        assert q["doc"]["text"] and q["q"]["id"] == "q0001"
        req = urllib.request.Request(base + "/api/review", data=json.dumps({"id": "q0001", "action": "accept", "reviewer": "Lan"}).encode("utf-8"), method="POST")
        assert json.loads(urllib.request.urlopen(req).read().decode("utf-8"))["status"] == "accepted"
    finally:
        srv.shutdown()

"""Sinh câu hỏi: chọn đơn vị, hậu xử lý (định vị quote, loại tự động), dry-run, hết quota/chạy tiếp. LLM giả, không gọi mạng."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.evaluation import testset as T  # noqa: E402
from rag.evaluation import testset_gen as G  # noqa: E402

QC = ("QUYẾT ĐỊNH\nĐiều 1. Ban hành kèm theo Quyết định này Quy chế.\n\nQuy chế\nĐiều 1. Phạm vi điều chỉnh\nQuy chế này áp dụng cho sinh viên đại học chính quy của Trường.\n"
      "Điều 9. Tổ chức đăng ký học\n1. Trước khi bắt đầu mỗi học kỳ, sinh viên được cố vấn học tập hướng dẫn đăng ký học tập trên hệ thống của Trường.\n"
      "2. Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính và tối đa 12 tín chỉ trong học kỳ phụ theo kế hoạch đào tạo.\n"
      "3. Sinh viên nộp đơn xin rút học phần tại phòng Đào tạo trong vòng hai tuần đầu của học kỳ để không bị tính học phí.\n"
      "Điều 10. Thi kết thúc học phần\n1. Sinh viên phải có mặt trước giờ thi 15 phút và mang theo thẻ sinh viên hoặc căn cước công dân.\n"
      "2. Sinh viên vắng mặt không có lý do chính đáng được tính điểm không cho bài thi đó theo quy định.\n")
TABLE = ("Bảng học phần\n\n| STT | Tên học phần | Mã học phần | Số tín chỉ |\n|---|---|---|---|\n| 1 | Toán cao cấp | MA101 | 3 |\n| 2 | Vật lý đại cương | PH101 | 3 |\n"
         "| 3 | Lập trình cơ bản | IT101 | 4 |\n| 4 | Tiếng Anh 1 | EN101 | 3 |\n| 5 | Triết học | PL101 | 3 |\n| 6 | Kinh tế vi mô | EC101 | 3 |\n")

UCFG = {"unit_chars": [120, 2800], "table_rows": [3, 4]}


@pytest.fixture
def docs(tmp_path, monkeypatch):
    (tmp_path / "qc.txt").write_text(QC, encoding="utf-8")
    (tmp_path / "tb.txt").write_text(TABLE, encoding="utf-8")
    monkeypatch.setattr(T, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(G, "vlm_doc_ids", lambda: set())
    T.clear_doc_cache()
    yield {"qc": {"doc_type": "quy_che", "title": "QUY CHẾ", "bac_dao_tao": "dai_hoc", "khoa_tu": 38, "khoa_den": 38},
           "tb": {"doc_type": "ctdt", "title": "CTĐT mẫu", "bac_dao_tao": "dai_hoc", "khoa_tu": None, "khoa_den": None}}
    T.clear_doc_cache()


def cfg(**over):
    c = {"seed": 42, "overgen": 0.4, "generation": {**UCFG, "expected_output_tokens": 200, "price_per_1m_tokens": {"input": None, "output": None}, "max_cost_usd": None},
         "auto_reject": {"copy_run_words": 8, "dup_ratio": 90, "fuzzy_locate_min": 0.9},
         "plan": {"quy_che": {"total": 4, "types": ["factoid", "dieu_kien", "nhieu_doan"]}, "ctdt": {"total": 2, "types": ["tra_bang"]}, "khau_ngu_share": 0.15},
         "version_dependent": {"n_with_khoa": 2, "n_without_khoa": 1, "khoa_by_version": {"2024": 36, "2025": 38, "2026": 40}},
         "out_of_scope": {"khong_lien_quan": 1, "cung_linh_vuc": 1, "ca_nhan": 1, "de_nham": 1}}
    c.update(over)
    return c


def test_units_follow_dieu_and_table_rows_independent_of_chunks(docs):
    qc = G.extract_units("qc", "quy_che", QC, UCFG)
    assert "dieu" in {u["kind"] for u in qc}
    d9 = next(u for u in qc if u["text"].startswith("Điều 9."))
    assert "Điều 10" not in d9["text"] and QC[d9["char_start"]:d9["char_end"]] == d9["text"]  # tọa độ gốc đúng
    tb = G.extract_units("tb", "ctdt", TABLE, UCFG)
    assert tb and all(u["kind"] == "table" for u in tb)
    assert all("STT" in u["header"] and "---" not in u["text"] and "STT" not in u["text"] for u in tb)  # header tách riêng, không nằm trong quote
    assert len(tb) == 2 and tb[0]["text"].count("\n") == 3                                            # 6 dòng chia 4 + 2


def test_select_units_deterministic_and_respects_types(docs):
    texts = {"qc": QC, "tb": TABLE}
    a = G.select_units(cfg(), docs, texts)
    b = G.select_units(cfg(), docs, texts)
    assert [u["unit_id"] + u["qtype"] for u in a] == [u["unit_id"] + u["qtype"] for u in b]
    assert a and all(u["kind"] == "table" for u in a if u["qtype"] == "tra_bang")
    spans: dict = {}
    for u in a:                                              # các đơn vị đã chọn không chồng nhau
        for s2, e2 in spans.get(u["doc_id"], []):
            assert u["char_end"] <= s2 or u["char_start"] >= e2
        spans.setdefault(u["doc_id"], []).append((u["char_start"], u["char_end"]))
    assert G.split_counts(25, ["factoid", "dieu_kien", "thu_tuc", "nhieu_doan", "khau_ngu"], 0.15)["khau_ngu"] == 4


def fake_call(qtype="factoid", unit_text_start="Điều 9."):
    u = next(x for x in G.extract_units("qc", "quy_che", QC, UCFG) if x["text"].startswith(unit_text_start))
    return {"call_id": f"gen|{u['unit_id']}|{qtype}", "kind": "gen", "qtype": qtype, "unit": {**u, "vlm": False}, "prompt": "p", "prompt_sha256": "sha"}


def raw_for(call, resp):
    return {"call_id": call["call_id"], "kind": call["kind"], "model": "m", "prompt_sha256": "sha", "temperature": 0, "response": json.dumps(resp, ensure_ascii=False)}


def build(calls, resps, docs, existing=None):
    return G.build_questions(calls, [raw_for(c, r) for c, r in zip(calls, resps)], cfg(), docs, existing)


def test_build_accepts_valid_question_with_located_span_and_overlap(docs):
    c = fake_call()
    ok, rej = build([c], [{"question": "Mỗi kỳ chính em đăng ký nhiều nhất mấy tín chỉ vậy?", "answer_ref": "25 tín chỉ",
                           "quotes": ["Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính"], "general_knowledge": False}], docs)
    assert len(ok) == 1 and not rej
    q = ok[0]
    e = q["expected"][0]
    assert QC[e["char_start"]:e["char_end"]] == e["quote"] and q["review"]["status"] == "pending" and q["id"] == "q0001"
    assert q["user_ctx"]["khoa"] == 38 and "K38" in q["version_note"] and q["gen"]["prompt_sha256"] == "sha" and q["lexical_overlap"] is not None


@pytest.mark.parametrize("resp,reason", [
    ({"question": "Em đăng ký bao nhiêu tín chỉ?", "answer_ref": "x", "quotes": ["Câu này hoàn toàn không có trong tài liệu đâu nhé"]}, "quote_khong_khop"),
    ({"question": "Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính là bao nhiêu", "answer_ref": "x",
      "quotes": ["Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính"]}, "chep_cum_dai"),
    ({"question": "Em đăng ký bao nhiêu tín chỉ?", "answer_ref": "x", "quotes": []}, "thieu_truong"),
])
def test_build_auto_rejects(docs, resp, reason):
    ok, rej = build([fake_call()], [resp], docs)
    assert not ok and rej[0]["reason"] == reason


def test_build_rejects_nhieu_doan_single_span_and_duplicates(docs):
    c1 = fake_call("nhieu_doan")
    ok, rej = build([c1], [{"question": "Rút học phần và đăng ký tối đa thế nào nhỉ em?", "answer_ref": "x",
                            "quotes": ["Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính"]}], docs)
    assert rej[0]["reason"] == "it_hon_2_span"
    c2 = fake_call("factoid", "Điều 10.")
    q = {"question": "Đi thi phải đến sớm bao lâu và mang giấy tờ gì ạ?", "answer_ref": "15 phút", "quotes": ["Sinh viên phải có mặt trước giờ thi 15 phút"]}
    first, _ = G.build_questions([c2], [raw_for(c2, q)], cfg(), docs, [])
    c3 = {**c2, "call_id": c2["call_id"] + "b"}
    second, rej2 = G.build_questions([c2, c3], [raw_for(c2, q), raw_for(c3, q)], cfg(), docs, first)
    assert not second and rej2[0]["reason"] == "trung_cau"          # trùng câu đã có; c2 đã build rồi thì không build lại


def test_flags_general_knowledge_and_idempotent_build(docs):
    c = fake_call()
    resp = {"question": "Mỗi kỳ chính em đăng ký nhiều nhất mấy tín chỉ vậy?", "answer_ref": "25", "general_knowledge": True,
            "quotes": ["Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính"]}
    ok, _ = build([c], [resp], docs)
    assert "kien_thuc_chung" in ok[0]["flags"]
    again, rej = G.build_questions([c], [raw_for(c, resp)], cfg(), docs, ok)
    assert not again and not rej                                    # chạy lại không sinh bản trùng


def test_oos_personal_requires_fake_name_and_version_questions(docs):
    oc = {"call_id": "oos|ca_nhan|0", "kind": "oos", "oos_kind": "ca_nhan", "hint": "h", "prompt": "p", "prompt_sha256": "s"}
    good = G.build_questions([oc], [raw_for(oc, {"questions": ["Sinh viên Nguyễn Văn A có bị buộc thôi học không?"]})], cfg(), docs)[0]
    assert good[0]["expected_behavior"] == "refuse" and good[0]["expected"] == [] and good[0]["oos_kind"] == "ca_nhan"
    bad = G.build_questions([oc], [raw_for(oc, {"questions": ["Bạn Trần Minh Quân bị kỷ luật chưa?"]})], cfg(), docs)
    assert bad[1][0]["reason"] == "ten_khong_gia"
    s9 = QC.index("2. Sinh viên được đăng ký tối đa 25")
    blk = {"s": s9, "e": s9 + 140, "dieu": "9"}
    vc = {"call_id": "ver|k#2", "kind": "version", "prompt": "p", "prompt_sha256": "s", "versions": {"2025": "qc", "2026": "qc"},
          "cand": {"key": "k#2", "num_diff": True, "blocks": {"2025": blk, "2026": blk}}}
    resp = {"question": "Một kỳ em được đăng ký tối đa mấy tín chỉ?", "answers": {
        "2025": {"quote": "Sinh viên được đăng ký tối đa 25 tín chỉ trong một học kỳ chính", "answer": "25"},
        "2026": {"quote": "tối đa 12 tín chỉ trong học kỳ phụ", "answer": "12"}}}
    ok, rej = G.build_questions([vc], [raw_for(vc, resp)], cfg(), docs)
    assert len(ok) == 2 and not rej
    withk = next(q for q in ok if q["expected_behavior"] == "answer")
    nok = next(q for q in ok if q["expected_behavior"] == "ask_clarify_or_multi_version")
    assert "khoa" in withk["user_ctx"] and len(withk["expected"]) == 1 and "khoa" not in nok["user_ctx"] and len(nok["expected"]) == 2


class FakeChat:
    temperature, temperature_applied = 0, True

    def __init__(self, quota_after=None):
        self.n, self.quota_after = 0, quota_after

    def complete(self, prompt):
        if self.quota_after is not None and self.n >= self.quota_after:
            raise G.QuotaExhausted("hết quota")
        self.n += 1
        return json.dumps({"question": f"c{self.n}"}), {"input_tokens": 100, "output_tokens": 50}


def test_dry_run_counts_and_quota_stop_then_resume(tmp_path):
    calls = [{"call_id": f"c{i}", "kind": "gen", "prompt": "xin chào " * 20, "prompt_sha256": "s"} for i in range(5)]
    c = cfg()
    info = G.dry_run(calls, c, "m")
    assert info["n_calls"] == 5 and info["input_tokens"] > 0 and info["cost_usd"] is None
    c["generation"]["price_per_1m_tokens"] = {"input": 1.0, "output": 2.0}
    assert G.dry_run(calls, c, "m")["cost_usd"] > 0
    raw = tmp_path / "raw.jsonl"
    r1 = G.run_calls(calls, FakeChat(quota_after=2), raw, "m", c, progress=lambda *_: None)
    assert r1["stopped"] == "quota" and len(G.read_raw(raw)) == 2                    # ghi ngay từng lần gọi
    done = {r["call_id"] for r in G.read_raw(raw)}
    assert G.dry_run(calls, c, "m", done)["n_calls"] == 3
    r2 = G.run_calls(calls, FakeChat(), raw, "m", c, progress=lambda *_: None)       # chạy tiếp, không gọi lại 2 lời gọi đã có
    assert r2["stopped"] is None and r2["n_new"] == 3 and len(G.read_raw(raw)) == 5


def test_openai_chat_drops_temperature_when_model_rejects_it():
    import httpx
    import openai

    class Completions:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            if "temperature" in kw:
                raise openai.BadRequestError("Unsupported value: 'temperature' does not support 0", response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)
            msg = type("M", (), {"content": "{}"})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()], "usage": type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()})()

    comp = Completions()
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": comp})()})()
    chat = G.OpenAIChat("m", 0, 100, client=client)
    text, _ = chat.complete("hi")
    assert text == "{}" and chat.temperature_applied is False and "temperature" not in comp.calls[-1] and "temperature" in comp.calls[0]
    assert comp.calls[0]["max_completion_tokens"] == 100


def test_version_diff_detects_changed_numbers():
    a = "Điều 9. Đăng ký\n1. Sinh viên đăng ký tối đa 25 tín chỉ mỗi học kỳ chính theo kế hoạch của Trường.\n"
    b = "Điều 9. Đăng ký\n1. Sinh viên đăng ký tối đa 20 tín chỉ mỗi học kỳ chính theo kế hoạch của Trường.\n"
    d = G.find_version_diffs({"2024": a, "2025": b, "2026": b}, pivot="2025")
    assert d and d[0]["num_diff"] and set(d[0]["blocks"]) == {"2024", "2025", "2026"}
    assert G.find_version_diffs({"2024": b, "2025": b, "2026": b}, pivot="2025") == []

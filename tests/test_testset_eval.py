"""Bộ chấm retrieval: phủ span, Recall@k/MRR/budget trên ví dụ dựng tay, cổng kiểm index, ngưỡng từ chối. Không cần Qdrant/mạng."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.evaluation import retrieval_eval as E  # noqa: E402


def ix_with(chunks: dict, parents: dict | None = None) -> E.ChunkIndex:
    ix = E.ChunkIndex()
    ix.chunks = {k: {"doc_id": v[0], "cs": v[1], "ce": v[2], "elen": v[3] if len(v) > 3 else (v[2] - v[1]), "parent": None, "content": v[4] if len(v) > 4 else None}
                 for k, v in chunks.items()}
    ix.parents = {k: {"doc_id": v[0], "cs": v[1], "ce": v[2], "elen": v[2] - v[1], "content": None} for k, v in (parents or {}).items()}
    return ix


Q = {"expected": [{"doc_id": "A", "char_start": 100, "char_end": 200, "quote": "q1"}, {"doc_id": "A", "char_start": 500, "char_end": 600, "quote": "q2"}]}
IX = ix_with({"c_miss": ("A", 0, 90), "c_half": ("A", 150, 400), "c_full1": ("A", 90, 210), "c_other": ("B", 100, 200), "c_full2": ("A", 480, 700),
              "c_small": ("A", 100, 140)})


def test_coverage_threshold_and_doc_id_must_match():
    # c_half phủ 50/100 = 0.5 -> đúng bằng ngưỡng => trúng; c_small phủ 0.4 => không; c_other khác doc => 0
    m = E.score_question(Q, ["c_miss", "c_other", "c_small", "c_half"], [], IX, 0.5)
    assert m["first_hit_rank"] == 4 and m["mrr"] == 0.25
    assert m["recall@3"] == 0.0 and m["recall@5"] == 0.5


def test_recall_at_k_over_multiple_spans_and_mrr():
    m = E.score_question(Q, ["c_miss", "c_full1", "c_other", "c_full2"], [], IX, 0.5)
    assert m["mrr"] == 0.5                      # chunk trúng đầu tiên ở hạng 2
    assert m["recall@1"] == 0.0 and m["recall@3"] == 0.5 and m["recall@5"] == 1.0   # span 2 chỉ được phủ ở hạng 4
    none = E.score_question(Q, ["c_miss", "c_other"], [], IX, 0.5)
    assert none["mrr"] == 0.0 and none["first_hit_rank"] is None and none["recall@5"] == 0.0


def test_recall_at_budget_uses_union_of_context_items_and_c3_parents():
    ix = ix_with({"x1": ("A", 100, 160), "x2": ("A", 150, 210)}, {"P1": ("A", 480, 700)})
    ctx = [{"id": "x1", "parent": False, "truncated": False, "text": "t"}, {"id": "x2", "parent": False, "truncated": False, "text": "t"},
           {"id": "P1", "parent": True, "truncated": False, "text": "t"}]
    m = E.score_question(Q, ["x1"], ctx, ix, 0.5)
    assert m["recall@budget"] == 1.0            # span 1 phủ bởi HỢP x1+x2 (không chunk nào đủ), span 2 phủ bởi parent
    assert m["recall@1"] == 0.5                 # x1 phủ 60/100 span 1 (>= 0.5) nhưng không phủ span 2
    only_p = E.score_question(Q, ["x1"], ctx[2:], ix, 0.5)
    assert only_p["recall@budget"] == 0.5


def test_truncated_context_item_covers_proportionally():
    ix = ix_with({"t1": ("A", 100, 200, 1000)})
    q = {"expected": [{"doc_id": "A", "char_start": 100, "char_end": 200, "quote": "q"}]}
    half = [{"id": "t1", "parent": False, "truncated": True, "text": "x" * 500}]      # còn 50% chữ => phủ 0.5
    tiny = [{"id": "t1", "parent": False, "truncated": True, "text": "x" * 200}]       # còn 20% => không đủ
    assert E.score_question(q, [], half, ix, 0.5)["recall@budget"] == 1.0
    assert E.score_question(q, [], tiny, ix, 0.5)["recall@budget"] == 0.0


def test_recall_at_1_is_exact_for_hit_at_top():
    m = E.score_question({"expected": [Q["expected"][0]]}, ["c_full1", "c_miss"], [], IX, 0.5)
    assert (m["recall@1"], m["recall@3"], m["mrr"]) == (1.0, 1.0, 1.0)


def test_text_coverage_mode_for_c2_novlm():
    ix = ix_with({"n1": ("A", 0, 0, 10, "Mã học phần MA101 Toán cao cấp 3 tín chỉ"), "n2": ("A", 0, 0, 10, "Lịch thi học kỳ I năm học 2025")})
    q = {"expected": [{"doc_id": "A", "char_start": 1, "char_end": 2, "quote": "| 1 | Toán cao cấp | MA101 | 3 |"}]}
    m = E.score_question(q, ["n2", "n1"], [{"id": "n1", "text": "Mã học phần MA101 Toán cao cấp 3 tín chỉ", "parent": False}], ix, 0.5, "text")
    assert m["first_hit_rank"] == 2 and m["recall@budget"] == 1.0
    assert E.text_coverage("hoàn toàn khác", "| 1 | Toán cao cấp | MA101 | 3 |") < 0.5


def test_wrong_version_detection():
    q = {"expected": [{"doc_id": "V2025"}]}
    versions = {"V2024", "V2025", "V2026"}
    assert E.wrong_version_top1(q, ["V2024", "V2025"], versions) is True
    assert E.wrong_version_top1(q, ["V2025", "V2024"], versions) is False
    assert E.wrong_version_top1(q, ["X"], versions) is False
    assert E.wrong_version_top1({"expected": [{"doc_id": "Z"}]}, ["V2024"], versions) is None


def test_threshold_curve_and_pick():
    pos = [5.0, 4.0, 3.0, 2.0, 1.0]      # câu có đáp án: điểm cao
    neg = [-3.0, -2.0, 0.5, 1.5]         # câu ngoài phạm vi: điểm thấp (một câu 1.5 lẫn vào)
    cv = E.threshold_curve(pos, neg)
    lo, hi = cv[0], cv[-1]
    assert lo["refuse_correct"] == 0 and lo["refuse_wrong"] == 0 and hi["refuse_correct"] == 1 and hi["refuse_wrong"] == 1   # t thấp nhất không từ chối ai; cao nhất từ chối hết
    pick = E.pick_threshold(cv, max_wrong=0.0)
    assert pick["refuse_wrong"] == 0 and pick["refuse_correct"] == 0.75 and 0.5 < pick["threshold"] <= 1.0
    assert E.pick_threshold(cv, 0.2)["refuse_correct"] == 1.0                         # cho phép 1/5 từ chối nhầm => từ chối đúng cả 4 câu
    assert E.threshold_curve([], []) == []


def test_index_gate_blocks_when_frozen_differs_from_last_index(tmp_path):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "c1_chunks.jsonl").write_text("{}\n", encoding="utf-8")
    sha = E.sha256_file(chunks / "c1_chunks.jsonl")
    frozen = tmp_path / "FROZEN.md"
    frozen.write_text(f"| c1_chunks.jsonl | 1 | 3 | `{sha}` |\n", encoding="utf-8")
    log = tmp_path / "usage.jsonl"
    old = "0" * 64
    log.write_text(json.dumps({"event": "chunk_file", "file": "c1_chunks.jsonl", "sha256": old}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Qdrant chưa index lại"):
        E.check_index_gate(frozen, log, chunks, ["c1_chunks.jsonl"])
    with log.open("a", encoding="utf-8") as f:                           # lần index MỚI NHẤT khớp => qua cổng
        f.write(json.dumps({"event": "chunk_file", "file": "c1_chunks.jsonl", "sha256": sha}) + "\n")
    assert E.check_index_gate(frozen, log, chunks, ["c1_chunks.jsonl"])["indexed"]["c1_chunks.jsonl"] == sha
    (chunks / "c1_chunks.jsonl").write_text("{\"a\":1}\n", encoding="utf-8")   # file trên đĩa bị đổi sau khi index
    with pytest.raises(SystemExit, match="lệch FROZEN"):
        E.check_index_gate(frozen, log, chunks, ["c1_chunks.jsonl"])
    with pytest.raises(SystemExit, match="chưa có bản ghi index"):
        E.check_index_gate(frozen, tmp_path / "none.jsonl", chunks, ["c1_chunks.jsonl"])


class FakeRes:
    def __init__(self, ranked, ctx, timings=None, logit=None):
        self.candidates = {"ranked": [{"rank": i + 1, "chunk_id": c, "doc_id": "A"} for i, c in enumerate(ranked)],
                           "dense": [{"score": 0.61}], "bm25": [{"score": 7.0}], "rrf": [{"score": 0.03}]}
        self.context = {"items": ctx}
        self.timings = timings or {"dense": 0.1, "rerank": 0.5}
        self.max_rerank_logit = logit


class FakeRt:
    def __init__(self):
        self.calls = 0

    def retrieve(self, q, config, mode, ctx):
        self.calls += 1
        return FakeRes(["c_full1", "c_full2"], [{"id": "c_full1", "parent": False, "truncated": False, "text": "t"}], logit=2.5)


def test_run_cell_scores_answer_and_records_signals_for_oos():
    q = {"id": "q1", "question": "?", "expected_behavior": "answer", "doc_type": "quy_che", "type": "factoid", "split": "dev", "flags": ["phu_thuoc_khoa"], **Q}
    rec = E.run_cell(FakeRt(), "c2", "c2", "hybrid_rerank", q, IX, 0.5, "char", {"A", "B"})
    assert rec["scored"] and rec["metrics"]["recall@5"] == 1.0 and rec["metrics"]["mrr"] == 1.0 and rec["signals"]["max_rerank_logit"] == 2.5
    assert rec["tags"] == ["phu_thuoc_khoa"] and rec["version_hit@5"] is True and rec["wrong_version_top1"] is False
    oos = {"id": "q2", "question": "thời tiết", "expected_behavior": "refuse", "doc_type": "ngoai_pham_vi", "type": "ngoai_pham_vi", "split": "dev", "expected": []}
    r2 = E.run_cell(FakeRt(), "c2", "c2", "hybrid_rerank", oos, IX)
    assert r2["scored"] is False and r2["oos"] is True and r2["signals"]["top_dense"] == 0.61 and "metrics" not in r2


def test_aggregate_threshold_report_and_markdown():
    qs = [{"id": f"q{i}", "question": "?", "expected_behavior": "answer", "doc_type": "quy_che" if i < 2 else "ctdt", "type": "factoid", "split": "dev", "flags": [], **Q} for i in range(4)]
    oos = [{"id": f"o{i}", "question": "x", "expected_behavior": "refuse", "doc_type": "ngoai_pham_vi", "type": "ngoai_pham_vi", "split": "dev", "expected": []} for i in range(2)]

    class Rt2(FakeRt):
        def retrieve(self, q, config, mode, ctx):
            if q == "x":
                return FakeRes(["c_miss"], [], logit=-4.0)
            return FakeRes(["c_miss", "c_full1"], [], logit=3.0)

    rt = Rt2()
    per = []
    for q in qs + oos:
        q = dict(q, question="x" if q["id"].startswith("o") else "?")
        for mode in ("hybrid", "hybrid_rerank"):
            per.append(E.run_cell(rt, "c2", "c2", mode, q, IX))
    summ = E.aggregate(per)
    allrow = next(r for r in summ if r["kind"] == "all" and r["mode"] == "hybrid")
    assert allrow["n"] == 4 and allrow["mrr"] == 0.5 and allrow["recall@5"] == 0.5
    dt = {r["group"]: r["n"] for r in summ if r["kind"] == "doc_type" and r["mode"] == "hybrid"}
    assert dt == {"quy_che": 2, "ctdt": 2}
    table, curves = E.threshold_report(per)
    t = next(x for x in table if x["signal"] == "max_rerank_logit" and x["cfg"].endswith("hybrid_rerank"))
    assert t["n_pos"] == 4 and t["n_neg"] == 2 and t["pick"]["refuse_correct"] == 1.0 and t["pick"]["refuse_wrong"] == 0.0 and -4.0 < t["pick"]["threshold"] < 3.0
    run = {"run_id": "r", "split": "dev", "n_questions": 4, "n_oos": 2, "cover_thr": 0.5, "frozen_sha": "a" * 64, "questions_sha": "b" * 64, "rerank_fast": "onnx", "rerank_ref": "torch"}
    md = E.summary_md(run, summ, E.step_latency([r for r in per if r.get("scored")]), {"version": E.version_stats(per), "thresholds": table, "overlap": None})
    assert "Tổng thể theo cấu hình" in md and "recall@5 theo doc_type" in md and "Ngưỡng từ chối" in md and "Không chỉnh tham số trên tập test" in md


def test_caching_reranker_and_embedder_call_inner_once():
    class Inner:
        n = 0

        def score_logits(self, q, texts):
            Inner.n += len(texts)
            return [float(len(t)) for t in texts]

        def embed(self, t):
            Inner.n += 1
            return [1.0]

    rr = E.CachingReranker(Inner())
    assert rr.score_logits("q", ["a", "bb"]) == [1.0, 2.0] and rr.score_logits("q", ["bb", "a", "ccc"]) == [2.0, 1.0, 3.0] and Inner.n == 3
    em = E.CachedEmbedder(Inner())
    em.embed("x")
    em.embed("x")
    assert Inner.n == 4


def test_chunk_index_loads_jsonl_with_parents(tmp_path):
    ch = tmp_path / "c.jsonl"
    ch.write_text(json.dumps({"chunk_id": "a::1", "embed_text": "abc", "content": "ab", "metadata": {"doc_id": "a", "char_start": 1, "char_end": 9, "parent_id": "a::d1"}}) + "\n", encoding="utf-8")
    pa = tmp_path / "p.jsonl"
    pa.write_text(json.dumps({"parent_id": "a::d1", "embed_text": "abcdef", "content": "abcdef", "metadata": {"doc_id": "a", "char_start": 0, "char_end": 20}}) + "\n", encoding="utf-8")
    ix = E.ChunkIndex.load(ch, pa, with_content=True)
    assert ix.chunks["a::1"]["cs"] == 1 and ix.chunks["a::1"]["content"] == "ab" and ix.parents["a::d1"]["ce"] == 20

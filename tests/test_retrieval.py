"""Test tầng retrieval: không gọi mạng; Qdrant dùng QdrantClient(":memory:"); embedder và reranker giả."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

from rag.embedding import bm25
from rag.embedding.qdrant_store import ensure_collection, load_parents, make_payload, point_id, upsert_points
from rag.retrieval import normalize as N
from rag.retrieval.context import build_context
from rag.retrieval.filters import build_filters
from rag.retrieval.fusion import dedup, rrf
from rag.retrieval.query_parser import parse_query
from rag.retrieval.retriever import Retriever

DEFAULTS = {"status": "hieu_luc", "in_scope": True, "bac_dao_tao": "dai_hoc"}
SW = bm25.load_stopwords(Path("configs/stopwords_vi.txt"))


# ------------------------------------------------------------------------------------------------ query_parser
@pytest.mark.parametrize("q,expect", [("Học phí học lại khóa 38?", 38), ("học phí khoá 38", 38), ("K38 đóng bao nhiêu", 38), ("k38 đóng",
                         38), ("sinh viên K 38", 38), ("K35, 36, 37 học phí", [35, 36, 37]), ("khóa 35 và 36", [35, 36]), ("lớp K38A1", None),
                         ("học kỳ 1", None)])
def test_khoa_variants(q, expect):
    assert parse_query(q).khoa == expect


@pytest.mark.parametrize("q,bac", [("học phí thạc sĩ", "sau_dai_hoc"), ("tuyển sinh cao học", "sau_dai_hoc"), ("nghiên cứu sinh", "sau_dai_hoc"),
                                   ("hệ liên thông", "lien_thong"), ("vừa làm vừa học", "vua_lam_vua_hoc"), ("đăng ký tín chỉ", None)])
def test_bac(q, bac):
    assert parse_query(q).bac_dao_tao == bac


@pytest.mark.parametrize("q,hk", [("học kỳ I", "hk1"), ("HK1", "hk1"), ("kỳ 1", "hk1"), ("học kỳ II", "hk2"), ("học kì 2", "hk2"),
                                  ("HK III", "hk3"), ("học kỳ phụ", "hkphu"), ("học kỳ hè", "hkhe"), ("năm học 2025", None)])
def test_hoc_ky(q, hk):
    assert parse_query(q).hoc_ky == hk


@pytest.mark.parametrize("q", ["năm học 2025 - 2026", "2025-2026", "2025–2026", "2025 — 2026"])
def test_nam_hoc(q):
    assert parse_query(q).nam_hoc == "2025_2026"


def test_ma_hoc_phan():
    assert parse_query("Học phần AE321 và MAT101 bao nhiêu tín chỉ").ma_hoc_phan == ["AE321", "MAT101"]
    assert parse_query("ae321").ma_hoc_phan == [] and parse_query("K38 HK1").ma_hoc_phan == []


def test_query_over_ctx():
    pq = parse_query("học phí khóa 39", {"khoa": 38, "bac_dao_tao": "dai_hoc"})
    assert pq.khoa == 39 and pq.flags["khoa"] == "query" and pq.flags["bac_dao_tao"] == "ctx" and pq.bac_dao_tao == "dai_hoc"
    pq = parse_query("học phí", {"khoa": 38})
    assert pq.khoa == 38 and pq.flags["khoa"] == "ctx"
    assert parse_query("học phí thạc sĩ", {"bac_dao_tao": "dai_hoc"}).bac_dao_tao == "sau_dai_hoc"


# ------------------------------------------------------------------------------------------------ chuẩn hóa BM25
def test_normalize_same_tokens_index_and_query():
    doc = bm25.tokenize("THÔNG BÁO Lịch thi học kỳ I, năm học 2025 - 2026 dành cho khóa 38", SW)
    qry = bm25.tokenize("Lịch thi HK1 năm học 2025-2026 K38", SW)
    for t in ("hk1", "nh_2025_2026", "2025", "2026", "khoa_38"):
        assert t in doc and t in qry, t
    assert "học_kỳ" in doc  # giữ cả từ gốc
    assert bm25.tokenize("kỳ phụ", SW).count("hkphu") == 1 and "hkhe" in bm25.tokenize("học kỳ hè", SW)
    assert "hk1" not in bm25.tokenize("học kỳ II", SW)
    assert N.domain_tokens("lớp K38A1") == []


# ------------------------------------------------------------------------------------------------ RRF, khử trùng lặp
def test_rrf_formula():
    out = dict(rrf({"d": ["a", "b", "c"], "s": ["b", "c", "d"]}, 60))
    assert out["a"] == pytest.approx(1 / 61) and out["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert out["c"] == pytest.approx(1 / 63 + 1 / 62) and out["d"] == pytest.approx(1 / 63)
    assert [k for k, _ in rrf({"d": ["a", "b", "c"], "s": ["b", "c", "d"]}, 60)] == ["b", "c", "a", "d"]


def test_dedup_keeps_best_rank():
    mk = lambda cid, t: {"chunk_id": cid, "payload": {"embed_text": t}}
    kept, dups = dedup([mk("x", "A"), mk("y", "B"), mk("z", "A"), mk("w", "A")])
    assert [c["chunk_id"] for c in kept] == ["x", "y"] and dups == [{"kept": "x", "dropped": ["z", "w"]}]


# ------------------------------------------------------------------------------------------------ bộ lọc
def test_filters_default_and_priority():
    f, a = build_filters(parse_query("học phí"), DEFAULTS)
    assert a["bac_dao_tao"] == "dai_hoc" and a["status"] == "hieu_luc" and a["in_scope"] is True and a["khoa"] is None
    f, a = build_filters(parse_query("học phí thạc sĩ", {"bac_dao_tao": "dai_hoc"}), DEFAULTS)
    assert a["bac_dao_tao"] == "sau_dai_hoc"
    f, a = build_filters(parse_query("học phí khóa 39", {"khoa": 38}), DEFAULTS)
    assert a["khoa"] == 39 and a["nguon"]["khoa"] == "query"


# ------------------------------------------------------------------------------------------------ luồng retrieve (Qdrant in-memory)
def chunk(cid, text, doc="d1", khoa_tu=None, khoa_den=None, bac="dai_hoc", status="hieu_luc", parent=None, title="T", page=1):
    return {"chunk_id": cid, "config": "c2", "embed_text": f"[{title}] {text}", "content": text, "n_tokens": 10,
            "metadata": {"doc_id": doc, "doc_type": "quy_che", "title": title, "status": status, "in_scope": True, "bac_dao_tao": bac,
                         "khoa_tu": khoa_tu, "khoa_den": khoa_den, "nganh": None, "is_table": False, "is_preamble": False,
                         "parent_id": parent, "page_start": page, "page_end": page, "source_url": "http://x"}}


def vec_for(text: str) -> list[float]:
    v = [0.0] * 1536
    v[sum(map(ord, text)) % 1536] = 1.0
    return v


class FakeEmb:
    def embed(self, text):
        return vec_for(text)


class FakeRR:
    """Reranker giả: điểm = số từ chung với câu hỏi."""

    def __init__(self):
        self.calls = 0

    def score(self, q, texts):
        self.calls += 1
        qs = set(q.lower().split())
        return [float(len(qs & set(t.lower().split()))) for t in texts]


def make_retriever(chunks, tmp_path, parents=None, **rover):
    cl = QdrantClient(":memory:")
    ensure_collection(cl, "t_c2")
    toks = [bm25.tokenize(c["embed_text"], SW) for c in chunks]
    avg = sum(map(len, toks)) / len(toks)
    pts = []
    for c, tk in zip(chunks, toks):
        idx, val = bm25.doc_to_sparse(tk, avg, 1.2, 0.75)
        pts.append(models.PointStruct(id=point_id(c["chunk_id"]), payload=make_payload(c),
                                      vector={"dense_small": vec_for(c["embed_text"]), "bm25": models.SparseVector(indices=idx, values=val)}))
    upsert_points(cl, "t_c2", pts)
    dbp = tmp_path / "p.sqlite"
    if parents:
        load_parents(dbp, parents)
    rcfg = {"k_candidates": 10, "rrf_k": 60, "n_rerank": 10, "top_k": 3, "context_budget_tokens": 1500, "min_truncate_tokens": 20,
            "default_filters": DEFAULTS, **rover}
    cfg = {"qdrant": {"collections": {"c2": "t_c2", "c3": "t_c2"}, "parents_path": dbp}}
    return Retriever(cfg=cfg, rcfg=rcfg, client=cl, embedder=FakeEmb(), reranker=FakeRR())


def test_retrieve_modes_filters_dedup(tmp_path):
    cs = [chunk("a::1", "học phí học lại khóa 38 là 650.000 đồng", doc="hp38", khoa_tu=38, khoa_den=38),
          chunk("b::1", "học phí học lại khóa 39 là 700.000 đồng", doc="hp39", khoa_tu=39, khoa_den=39),
          chunk("c::1", "học phí thạc sĩ khóa 38", doc="ths", bac="sau_dai_hoc", khoa_tu=38, khoa_den=38),
          chunk("d::1", "quy chế cũ về học phí học lại", doc="cu", status="het_hieu_luc"),
          chunk("e::1", "học phí học lại khóa 38 là 650.000 đồng", doc="hp38b", khoa_tu=38, khoa_den=38, title="T"),
          chunk("f::1", "thông báo nghỉ học tạm thời")]
    cs[4]["embed_text"] = cs[0]["embed_text"]  # embed_text giống hệt a::1
    rt = make_retriever(cs, tmp_path)
    for mode in ("dense", "bm25", "hybrid", "hybrid_rerank"):
        res = rt.retrieve("Học phí học lại khóa 38 là bao nhiêu?", "c2", mode)
        ids = [c["chunk_id"] for c in res.final]
        assert {"a::1", "e::1"} & set(ids) and not {"b::1", "c::1", "d::1"} & set(ids), mode  # lọc khóa/bậc/trạng thái
        assert not ({"a::1", "e::1"} <= set(ids))  # khử trùng lặp
        assert res.filters["khoa"] == 38 and res.filters["bac_dao_tao"] == "dai_hoc"
        assert res.context["tokens"] <= res.context["budget"]
    res = rt.retrieve("Học phí học lại khóa 38 là bao nhiêu?", "c2", "hybrid_rerank")
    assert res.duplicates and res.duplicates[0]["dropped"] and res.max_rerank_score is not None
    assert [c["rerank"] for c in res.final] == sorted([c["rerank"] for c in res.final], reverse=True)
    assert set(res.candidates) >= {"dense", "bm25", "rrf", "rerank"} and {"embed", "dense", "sparse", "fusion", "rerank", "context"} <= set(res.timings)
    # user_ctx khóa 38 áp dụng khi câu hỏi không nêu; câu hỏi nêu khóa 39 thì ưu tiên câu hỏi
    assert {c["chunk_id"] for c in rt.retrieve("học phí học lại", "c2", "bm25", {"khoa": 38}).final} & {"a::1", "e::1"}
    ids39 = {c["chunk_id"] for c in rt.retrieve("học phí học lại khóa 39", "c2", "bm25", {"khoa": 38}).final}
    assert "b::1" in ids39 and not {"a::1", "e::1"} & ids39
    # bm25 bắt được mã học kỳ chuẩn hóa
    assert rt.retrieve("học phí", "c2", "bm25", {"bac_dao_tao": "sau_dai_hoc"}).final[0]["chunk_id"] == "c::1"


def test_dense_mode_does_not_call_reranker(tmp_path):
    rt = make_retriever([chunk("a::1", "văn bản một"), chunk("b::1", "văn bản hai")], tmp_path)
    rt.retrieve("văn bản", "c2", "hybrid")
    assert rt._reranker.calls == 0
    assert rt.retrieve("văn bản", "c2", "hybrid").max_rerank_score is None


# ------------------------------------------------------------------------------------------------ C3 parent + ngân sách
def test_c3_parent_expansion_and_budget(tmp_path):
    parents = [{"parent_id": "P1", "embed_text": "[T] " + "điều một " * 30, "content": "x", "n_tokens": 90,
                "metadata": {"doc_id": "d1", "page_start": 3, "page_end": 4, "source_url": "http://x"}},
               {"parent_id": "P2", "embed_text": "[T] " + "điều hai " * 30, "content": "y", "n_tokens": 90,
                "metadata": {"doc_id": "d2", "page_start": 7, "page_end": 7, "source_url": "http://y"}}]
    db = tmp_path / "p.sqlite"
    load_parents(db, parents)
    final = [{"chunk_id": "c1", "payload": {"embed_text": "[T] a", "parent_id": "P1"}},
             {"chunk_id": "c2", "payload": {"embed_text": "[T] b", "parent_id": "P2"}},
             {"chunk_id": "c3", "payload": {"embed_text": "[T] c", "parent_id": "P1"}}]
    ctx = build_context(final, "c3", 1500, 20, db)
    assert [i["id"] for i in ctx["items"]] == ["P1", "P2"] and ctx["items"][0]["children"] == ["c1", "c3"]  # gộp parent trùng, giữ thứ tự
    assert ctx["items"][0]["citation"]["page_start"] == 3 and ctx["items"][0]["citation"]["doc_id"] == "d1"
    small = build_context(final, "c3", 100, 20, db)  # ngân sách nhỏ: cắt, không vượt
    assert small["tokens"] <= 100 and small["items"][-1]["truncated"]
    c2 = build_context(final, "c2", 1500, 20, db)  # không phải c3: dùng chính chunk
    assert [i["id"] for i in c2["items"]] == ["c1", "c2", "c3"] and not any(i["parent"] for i in c2["items"])
    assert sqlite3.connect(str(db)).execute("select count(*) from parents").fetchone()[0] == 2

"""Test embedding/index: không gọi mạng, không cần Qdrant thật (QdrantClient(":memory:"), client OpenAI giả)."""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import openai
import pytest
from qdrant_client import QdrantClient, models

from rag.chunking.metadata import khoa_matches
from rag.embedding import bm25, indexer
from rag.embedding.openai_embedder import OpenAIEmbedder, QuotaExhausted, cache_key, make_batches
from rag.embedding.qdrant_store import (DENSE, build_filter, ensure_collection, load_parents, make_payload, point_id,
                                        sync_delete_stale, upsert_points, verify_collection)

DIM = 8


def make_cfg(tmp_path: Path, **over) -> dict:
    cfg = {"openai": {"models": {"small": {"name": "m-small", "dim": DIM}, "large": {"name": "m-large", "dim": DIM}},
                      "batch_size": 3, "max_tokens_per_request": 1000, "price_per_1m_tokens": {"small": 1.0, "large": None},
                      "max_cost_usd": 5},
           "cache_dir": tmp_path / "cache", "usage_log": tmp_path / "usage.jsonl",
           "qdrant": {"collections": {"c2": "t_c2"}, "parents_path": tmp_path / "p.sqlite", "upsert_batch": 4},
           "chunks": {}, "bm25": {"k1": 1.2, "b": 0.75, "stopwords": Path("configs/stopwords_vi.txt"), "stats_path": tmp_path / "bm.json"}}
    cfg.update(over)
    return cfg


class FakeClient:
    """Client OpenAI giả: ghi lại các lần gọi; `errors` là hàng đợi lỗi sẽ ném trước khi trả kết quả."""

    def __init__(self, errors=None, dim=DIM):
        self.calls, self.errors, self.dim = [], list(errors or []), dim
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, model, input):
        if self.errors:
            raise self.errors.pop(0)
        self.calls.append(list(input))
        data = [SimpleNamespace(index=i, embedding=[float((hash(t) % 7) + 1)] + [0.5] * (self.dim - 1)) for i, t in enumerate(input)]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=10 * len(input)))


def rate_limit(code: str | None) -> openai.RateLimitError:
    resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    body = {"error": {"code": code, "message": "x"}} if code else None
    return openai.RateLimitError("429", response=resp, body=body)


# ------------------------------------------------------------------------------------------------ embedder
def test_cache_hit_and_miss(tmp_path):
    cfg, fc = make_cfg(tmp_path), FakeClient()
    emb = OpenAIEmbedder(cfg, "small", client=fc, sleep=lambda s: None)
    texts = ["a b c", "d e f", "g h i", "a b c"]
    p = emb.plan(texts)
    assert (p["n_chunks"], p["n_unique"], p["n_missing"], p["n_cached"]) == (4, 3, 3, 0)
    emb.embed_missing(p, progress=lambda *_: None)
    assert sum(len(c) for c in fc.calls) == 3
    p2 = emb.plan(texts)  # chạy lại: không gọi thêm
    assert p2["n_missing"] == 0 and p2["tokens"] == 0
    emb.embed_missing(p2, progress=lambda *_: None)
    assert sum(len(c) for c in fc.calls) == 3
    p3 = emb.plan(texts + ["mới hoàn toàn"])
    assert p3["n_missing"] == 1
    emb.embed_missing(p3, progress=lambda *_: None)
    assert fc.calls[-1] == ["mới hoàn toàn"]
    assert len(emb.get_vectors(texts)) == 4
    # khóa cache theo mô hình
    assert cache_key("m-small", "x") != cache_key("m-large", "x")
    assert len(emb.usage_log.read_text(encoding="utf-8").splitlines()) == len(fc.calls)


def test_dry_run_does_not_call_api(tmp_path):
    rows = [{"chunk_id": f"d::{i}", "config": "c2", "embed_text": f"văn bản số {i}", "content": "x", "n_tokens": 3,
             "metadata": {"in_scope": True}} for i in range(5)]
    f = tmp_path / "c2_chunks.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    cfg = make_cfg(tmp_path, chunks={"c2": f})
    fc = FakeClient()
    emb = OpenAIEmbedder(cfg, "small", client=fc)
    out = indexer.run_index("c2", "small", yes=False, cfg=cfg, embedder=emb)
    assert out["dry_run"] and out["n_missing"] == 5 and out["tokens"] > 0 and fc.calls == []


def test_stop_on_insufficient_quota(tmp_path):
    cfg = make_cfg(tmp_path)
    fc = FakeClient(errors=[rate_limit("insufficient_quota")])
    emb = OpenAIEmbedder(cfg, "small", client=fc, sleep=lambda s: pytest.fail("không được retry khi hết quota"))
    msgs = []
    with pytest.raises(QuotaExhausted):
        emb.embed_missing(emb.plan(["a", "b", "c", "d"]), progress=msgs.append)
    assert any("HẾT QUOTA" in m for m in msgs)

    # batch đầu xong rồi mới hết quota: phần đã xong nằm trong cache, chạy lại chỉ gọi phần còn thiếu
    class Half(FakeClient):
        def _create(self, model, input):
            if len(self.calls) == 1:
                raise rate_limit("credit_balance_exhausted")
            return super()._create(model, input)
    fc2 = Half()
    emb2 = OpenAIEmbedder(make_cfg(tmp_path / "x"), "small", client=fc2, sleep=lambda s: None)
    texts = [f"t{i}" for i in range(7)]  # batch_size=3 -> 3 + 3 + 1
    with pytest.raises(QuotaExhausted):
        emb2.embed_missing(emb2.plan(texts), progress=lambda *_: None)
    assert emb2.plan(texts)["n_missing"] == 4
    fc2.calls.clear()
    fc3 = FakeClient()
    emb2._client = fc3
    emb2.embed_missing(emb2.plan(texts), progress=lambda *_: None)
    assert sum(len(c) for c in fc3.calls) == 4


def test_rate_limit_retries_with_backoff(tmp_path):
    sleeps = []
    fc = FakeClient(errors=[rate_limit("rate_limit_exceeded"), rate_limit(None)])
    emb = OpenAIEmbedder(make_cfg(tmp_path), "small", client=fc, sleep=sleeps.append)
    emb.embed_missing(emb.plan(["a"]), progress=lambda *_: None)
    assert len(sleeps) == 2 and all(s > 0 for s in sleeps) and len(fc.calls) == 1


def test_wrong_dim_rejected(tmp_path):
    emb = OpenAIEmbedder(make_cfg(tmp_path), "small", client=FakeClient(dim=DIM + 1))
    with pytest.raises(RuntimeError, match="chiều"):
        emb.embed_missing(emb.plan(["a"]), progress=lambda *_: None)


def test_over_budget_stops_before_calling(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["openai"]["max_cost_usd"] = 0.0000001
    fc = FakeClient()
    emb = OpenAIEmbedder(cfg, "small", client=fc)
    from rag.embedding.openai_embedder import OverBudget
    with pytest.raises(OverBudget):
        emb.embed_missing(emb.plan(["một văn bản khá dài để có token " * 20]), progress=lambda *_: None)
    assert fc.calls == []


def test_make_batches_limits():
    items = [(f"t{i}", 400) for i in range(5)]
    b = make_batches(items, batch_size=10, max_tokens=1000)
    assert [len(x) for x in b] == [2, 2, 1] and all(sum(n for _, n in x) <= 1000 for x in b)
    b = make_batches([(f"t{i}", 1) for i in range(7)], batch_size=3, max_tokens=1000)
    assert [len(x) for x in b] == [3, 3, 1]
    assert [len(x) for x in make_batches([("huge", 5000), ("a", 1)], 10, 1000)] == [1, 1]  # input quá lớn nằm riêng
    assert make_batches([], 3, 10) == []


# ------------------------------------------------------------------------------------------------ BM25
SW = bm25.load_stopwords(Path("configs/stopwords_vi.txt"))


def test_tokenize_fixed_sentence():
    toks = bm25.tokenize("Sinh viên được đăng ký tối đa 25 tín chỉ; học phần AE321, phí 650.000 đồng, điểm 4,0.", SW)
    assert toks == ["sinh_viên", "đăng_ký", "tối_đa", "25", "tín_chỉ", "học_phần", "ae321", "phí", "650.000", "đồng", "điểm", "4,0"]


def test_numbers_codes_dates_kept():
    toks = bm25.tokenize("Học phần AE321 hạn 25/3/2025, 4,0 điểm, 650.000 đồng, lớp K38A1.", SW)
    for t in ("ae321", "25/3/2025", "4,0", "650.000", "k38a1"):
        assert t in toks
    assert "," not in toks and "." not in toks
    assert "của" not in bm25.tokenize("quy chế của trường", SW)
    assert "không" in bm25.tokenize("không được nghỉ", SW)  # negation không bị coi là stopword


def test_token_id_reproducible():
    import hashlib
    assert bm25.token_id("ae321") == int.from_bytes(hashlib.blake2b(b"ae321").digest()[:4], "big") == 2205401357
    assert 0 <= bm25.token_id("tín_chỉ") < 2 ** 32


def test_bm25_formula():
    k1, b = 1.2, 0.75
    assert bm25.bm25_tf(3, 100, 80, k1, b) == pytest.approx(3 * 2.2 / (3 + 1.2 * (1 - 0.75 + 0.75 * 100 / 80)))
    assert bm25.bm25_tf(1, 80, 80, k1, b) == pytest.approx(1.0)  # dl == avgdl, tf=1 -> 1
    idx, val = bm25.doc_to_sparse(["a", "b", "a"], avgdl=3, k1=k1, b=b)
    d = dict(zip(idx, val))
    assert d[bm25.token_id("a")] == pytest.approx(2 * 2.2 / (2 + 1.2))
    assert d[bm25.token_id("b")] == pytest.approx(1.0)
    assert idx == sorted(idx)


def test_query_to_sparse_unit_values():
    sv = bm25.query_to_sparse("Học phần AE321 bao nhiêu tín chỉ?", SW)
    assert sv.values and all(v == 1.0 for v in sv.values)
    assert bm25.token_id("ae321") in sv.indices and len(set(sv.indices)) == len(sv.indices)


def test_collision_tracker(monkeypatch):
    monkeypatch.setattr(bm25, "token_id", lambda t: 7 if t in ("x", "y") else 9)
    tr = bm25.CollisionTracker()
    tr.add(["x", "z"])
    tr.add(["y"])
    assert tr.report()["n_collisions"] == 1


# ------------------------------------------------------------------------------------------------ uuid / indexer
def test_point_id_stable():
    assert point_id("doc::s000") == point_id("doc::s000") != point_id("doc::s001")
    assert str(__import__("uuid").UUID(point_id("x"))) == point_id("x")


def test_excluded_file_rejected(tmp_path):
    f = tmp_path / "excluded_chunks.jsonl"
    f.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Từ chối"):
        indexer.load_chunks(f)
    g = tmp_path / "c2_chunks.jsonl"
    g.write_text(json.dumps({"chunk_id": "a", "metadata": {"in_scope": False}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="in_scope"):
        indexer.load_chunks(g)
    real = Path("data/processed/chunks")
    from rag.embedding.settings import embedding_config
    assert not any("excluded" in str(p) for p in embedding_config()["chunks"].values()) and real.exists()


# ------------------------------------------------------------------------------------------------ Qdrant (in-memory)
def chunk(cid, status="hieu_luc", in_scope=True, khoa_tu=None, khoa_den=None, text="văn bản"):
    return {"chunk_id": cid, "config": "c2", "embed_text": f"[T] {text}", "content": text, "n_tokens": 5,
            "metadata": {"doc_id": cid.split("::")[0], "doc_type": "quy_che", "status": status, "in_scope": in_scope,
                         "bac_dao_tao": "dai_hoc", "khoa_tu": khoa_tu, "khoa_den": khoa_den, "nganh": None, "is_table": False,
                         "is_preamble": False}}


def point(c, dense=None):
    sv = models.SparseVector(indices=[1, 2], values=[1.0, 0.5])
    return models.PointStruct(id=point_id(c["chunk_id"]), payload=make_payload(c),
                              vector={DENSE["small"][0]: dense or [0.1] * 1536, "bm25": sv})


def test_collection_upsert_sync_idempotent():
    cl = QdrantClient(":memory:")
    assert ensure_collection(cl, "t") is True and ensure_collection(cl, "t") is False
    info = cl.get_collection("t")
    assert set(info.config.params.vectors) == {"dense_small", "dense_large"}
    assert info.config.params.sparse_vectors["bm25"].modifier == models.Modifier.IDF
    cs = [chunk(f"d::{i}") for i in range(5)]
    upsert_points(cl, "t", [point(c) for c in cs], batch=2)
    upsert_points(cl, "t", [point(c) for c in cs], batch=2)  # lặp lại: không tạo bản trùng
    assert cl.count("t").count == 5
    keep = {point_id(c["chunk_id"]) for c in cs[:3]}
    assert sync_delete_stale(cl, "t", keep) == 2 and cl.count("t").count == 3
    assert sync_delete_stale(cl, "t", keep) == 0
    v = verify_collection(cl, "t", 3, "small")
    assert v["ok"] and v["in_scope_false"] == 0 and len(v["sample"]) == 3


def test_payload_filters():
    cl = QdrantClient(":memory:")
    ensure_collection(cl, "t")
    cs = [chunk("a::0", khoa_tu=None, khoa_den=None), chunk("b::0", khoa_tu=None, khoa_den=37), chunk("c::0", khoa_tu=39, khoa_den=None),
          chunk("d::0", khoa_tu=36, khoa_den=38), chunk("e::0", status="het_hieu_luc"), chunk("f::0", in_scope=False)]
    upsert_points(cl, "t", [point(c) for c in cs])

    def ids(**kw):
        recs, _ = cl.scroll("t", scroll_filter=build_filter(**kw), limit=100)
        return {r.payload["chunk_id"] for r in recs}

    assert ids() == {"a::0", "b::0", "c::0", "d::0"}  # mặc định: hieu_luc + in_scope
    assert "e::0" in ids(status=None) and "f::0" not in ids(status=None)
    assert "f::0" in ids(in_scope=None)
    for k in (30, 36, 37, 38, 39, 45):  # khớp với khoa_matches của metadata (null một đầu = không giới hạn)
        expect = {c["chunk_id"] for c in cs[:4] if khoa_matches(c["metadata"]["khoa_tu"], c["metadata"]["khoa_den"], k)}
        assert ids(khoa=k) == expect, k
    assert ids(khoa=38) == {"a::0", "d::0"} and ids(khoa=37) == {"a::0", "b::0", "d::0"}


def test_chunk_file_sha_and_change_detection(tmp_path):
    f = tmp_path / "c2_chunks.jsonl"
    f.write_text(json.dumps({"chunk_id": "a", "metadata": {"in_scope": True}}) + "\n", encoding="utf-8")
    rows, sha = indexer.load_chunks_sha(f)
    assert len(rows) == 1 and len(sha) == 64
    indexer.check_unchanged(f, sha)
    f.write_text(f.read_text(encoding="utf-8") + json.dumps({"chunk_id": "b", "metadata": {"in_scope": True}}) + "\n", encoding="utf-8")
    with pytest.raises(indexer.ChunkFileChanged):
        indexer.check_unchanged(f, sha)
    cfg = make_cfg(tmp_path)
    indexer.log_file_sha(cfg, "c2", f, sha, 1)
    assert json.loads(cfg["usage_log"].read_text(encoding="utf-8"))["sha256"] == sha


def test_verify_filters_in_memory():
    cl = QdrantClient(":memory:")
    ensure_collection(cl, "t")
    cs = [chunk("a::0"), chunk("b::0", khoa_den=37), chunk("c::0", khoa_tu=38, khoa_den=38), chunk("d::0", khoa_tu=39, khoa_den=99),
          chunk("e::0", status="het_hieu_luc")]
    for c in cs:
        c["metadata"]["title"] = "T " + c["chunk_id"]
    upsert_points(cl, "t", [point(c) for c in cs])
    r = indexer.verify_filters(cl, "t")
    assert r["ok"], r["errors"]
    assert r["report"][37]["count"] == 3 and r["report"][38]["count"] == 3 and r["report"][39]["count"] == 3


def test_frozen_check(tmp_path):
    cfg = make_cfg(tmp_path)
    fz = tmp_path / "FROZEN.md"
    with pytest.raises(SystemExit, match="không khớp FROZEN.md"):
        indexer.check_frozen(cfg, fz, {"c2_chunks.jsonl": "a" * 64})  # không có FROZEN.md
    fz.write_text("# Frozen\n| c2_chunks.jsonl | " + "a" * 64 + " |\n- c1_chunks.jsonl: " + "b" * 64 + "\n", encoding="utf-8")
    assert indexer.check_frozen(cfg, fz, {"c2_chunks.jsonl": "a" * 64})["c1_chunks.jsonl"] == "b" * 64
    with pytest.raises(SystemExit, match="không khớp FROZEN.md"):
        indexer.check_frozen(cfg, fz, {"c1_chunks.jsonl": "c" * 64})  # lệch
    with pytest.raises(SystemExit, match="không khớp FROZEN.md"):
        indexer.check_frozen(cfg, fz, {"c3_chunks.jsonl": "c" * 64})  # thiếu mục
    assert sum('"event": "frozen"' in l for l in cfg["usage_log"].read_text(encoding="utf-8").splitlines()) == 1

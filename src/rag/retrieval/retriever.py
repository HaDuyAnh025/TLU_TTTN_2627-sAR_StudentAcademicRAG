"""Điều phối retrieval: parse -> lọc -> dense/bm25 -> RRF -> khử trùng lặp -> rerank -> top_k -> context.

retrieve(query, config="c2", mode="hybrid_rerank", user_ctx=None) -> RetrievalResult
mode: dense | bm25 | hybrid | hybrid_rerank | hybrid_rerank_fused (xem fusion.fuse_with_rerank). CHƯA gọi LLM sinh câu trả lời.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from rag.embedding.qdrant_store import connect
from rag.embedding.settings import embedding_config
from rag.retrieval import context as ctxmod
from rag.retrieval.dense import QueryEmbedder, search_dense
from rag.retrieval.filters import build_filters
from rag.retrieval.fusion import dedup, fuse_with_rerank, rrf
from rag.retrieval.query_parser import ParsedQuery, parse_query
from rag.retrieval.reranker import get_reranker, sigmoid
from rag.retrieval.settings import retrieval_config
from rag.retrieval.sparse import search_sparse

MODES = ("dense", "bm25", "hybrid", "hybrid_rerank", "hybrid_rerank_fused")
RERANK_MODES = ("hybrid_rerank", "hybrid_rerank_fused")


@dataclass
class RetrievalResult:
    query: str
    config: str
    mode: str
    parsed_query: ParsedQuery
    filters: dict
    candidates: dict[str, list[dict]] = field(default_factory=dict)   # giai đoạn -> [{rank, chunk_id, score, breadcrumb, ...}]
    final: list[dict] = field(default_factory=list)                   # top_k (đầy đủ payload)
    context: dict = field(default_factory=dict)
    max_rerank_score: float | None = None                             # sigmoid(logit) cao nhất
    max_rerank_logit: float | None = None                             # logit thô cao nhất (trước sigmoid); CHƯA đặt ngưỡng từ chối
    duplicates: list[dict] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)           # giây

    def to_dict(self) -> dict:
        d = asdict(self)
        for f in d["final"]:
            f["payload"] = {k: v for k, v in f["payload"].items() if k not in ("embed_text", "content")}
        return d


def _cand(p) -> dict:
    return {"point_id": str(p.id), "chunk_id": p.payload["chunk_id"], "score": float(p.score), "payload": p.payload}


def _row(rank: int, c: dict, score_key: str = "score") -> dict:
    return {"rank": rank, "chunk_id": c["chunk_id"], "score": round(float(c[score_key]), 4), "doc_id": c["payload"]["doc_id"],
            "khoa": [c["payload"].get("khoa_tu"), c["payload"].get("khoa_den")], "breadcrumb": ctxmod.breadcrumb(c["payload"]["embed_text"])}


class Retriever:
    def __init__(self, cfg: dict | None = None, rcfg: dict | None = None, client=None, embedder=None, reranker=None) -> None:
        self.cfg, self.rcfg = cfg or embedding_config(), rcfg or retrieval_config()
        self.client = client or connect(self.cfg["qdrant"]["url"])
        self._embedder, self._reranker = embedder, reranker

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = QueryEmbedder(self.cfg)
        return self._embedder

    @property
    def reranker(self):
        if self._reranker is None:
            self._reranker = get_reranker(self.rcfg)
        return self._reranker

    @reranker.setter
    def reranker(self, value) -> None:
        self._reranker = value

    def first_stage(self, query: str, config: str, mode: str, user_ctx: dict | None):
        """parse -> lọc -> truy xuất -> (RRF) -> khử trùng lặp. Trả (res, ranked, score_key, timings); chưa rerank."""
        r, name = self.rcfg, self.cfg["qdrant"]["collections"][config]
        tm: dict[str, float] = {}
        pq = parse_query(query, user_ctx)
        flt, applied = build_filters(pq, r["default_filters"])
        res = RetrievalResult(query=query, config=config, mode=mode, parsed_query=pq, filters=applied)
        k = r["k_candidates"]
        by_id: dict[str, dict] = {}
        lists: dict[str, list[str]] = {}
        if mode in ("dense", "hybrid", *RERANK_MODES):
            t = time.perf_counter()
            vec = self.embedder.embed(pq.text)
            tm["embed"] = time.perf_counter() - t
            t = time.perf_counter()
            hits = [_cand(p) for p in search_dense(self.client, name, vec, flt, k)]
            tm["dense"] = time.perf_counter() - t
            lists["dense"] = [h["point_id"] for h in hits]
            by_id.update({h["point_id"]: h for h in hits})
            res.candidates["dense"] = [_row(i, h) for i, h in enumerate(hits, 1)]
        if mode in ("bm25", "hybrid", *RERANK_MODES):
            t = time.perf_counter()
            hits = [_cand(p) for p in search_sparse(self.client, name, pq.text, flt, k)]
            tm["sparse"] = time.perf_counter() - t
            lists["bm25"] = [h["point_id"] for h in hits]
            by_id.update({h["point_id"]: h for h in hits})
            res.candidates["bm25"] = [_row(i, h) for i, h in enumerate(hits, 1)]
        t = time.perf_counter()
        if mode in ("hybrid", *RERANK_MODES):
            ranked = [{**by_id[pid], "rrf": s} for pid, s in rrf(lists, r["rrf_k"])]
            key = "rrf"
            res.candidates["rrf"] = [_row(i, c, "rrf") for i, c in enumerate(ranked, 1)]
        else:
            ranked, key = [by_id[pid] for pid in next(iter(lists.values()))], "score"
        ranked, res.duplicates = dedup(ranked)  # trước rerank: embed_text giống hệt chỉ giữ bản xếp hạng cao nhất
        tm["fusion"] = time.perf_counter() - t
        return res, ranked, key, tm

    def retrieve(self, query: str, config: str = "c2", mode: str = "hybrid_rerank", user_ctx: dict | None = None) -> RetrievalResult:
        if mode not in MODES:
            raise ValueError(f"mode phải thuộc {MODES}")
        r = self.rcfg
        res, ranked, key, tm = self.first_stage(query, config, mode, user_ctx)
        pq = res.parsed_query
        if mode in RERANK_MODES:
            t = time.perf_counter()
            pool = ranked[: r["n_rerank"]]
            texts = [c["payload"]["embed_text"] for c in pool]
            rr = self.reranker
            if hasattr(rr, "score_logits"):
                logits = rr.score_logits(pq.text, texts)
                probs = [sigmoid(x) for x in logits]
            else:  # reranker giả chỉ có score()
                probs = rr.score(pq.text, texts)
                logits = [None] * len(probs)
            if mode == "hybrid_rerank":
                for c, s, lg in zip(pool, probs, logits):
                    c["rerank"], c["rerank_logit"] = s, lg
                pool.sort(key=lambda c: -c["rerank"])
                key = "rerank"
            else:
                lg_by = {c["chunk_id"]: lg for c, lg in zip(pool, logits)}
                pool = fuse_with_rerank(pool, probs, pq, r.get("fusion_w", 0.7), r.get("struct_bonus", 0.003), 60)
                for c in pool:
                    c["rerank_logit"] = lg_by[c["chunk_id"]]
                key = "fused"
            tm["rerank"] = time.perf_counter() - t
            res.candidates["rerank"] = [_row(i, c, "rerank") for i, c in enumerate(sorted(pool, key=lambda c: -c["rerank"]), 1)]
            top = max(pool, key=lambda c: c["rerank"]) if pool else None
            res.max_rerank_score = top["rerank"] if top else None
            res.max_rerank_logit = top.get("rerank_logit") if top else None
            ranked = pool
        res.candidates["ranked"] = [_row(i, c, key) for i, c in enumerate(ranked, 1)]  # thứ hạng cuối của chế độ này (sau khử trùng lặp)
        res.final = [{**c, "final_score": c[key]} for c in ranked[: r["top_k"]]]
        t = time.perf_counter()
        res.context = ctxmod.build_context(res.final, config, r["context_budget_tokens"], r.get("min_truncate_tokens", 100),
                                           self.cfg["qdrant"]["parents_path"])
        tm["context"] = time.perf_counter() - t
        res.timings = {k_: round(v, 4) for k_, v in tm.items()}
        return res


_default: Retriever | None = None


def retrieve(query: str, config: str = "c2", mode: str = "hybrid_rerank", user_ctx: dict | None = None) -> RetrievalResult:
    global _default
    if _default is None:
        _default = Retriever()
    return _default.retrieve(query, config, mode, user_ctx)

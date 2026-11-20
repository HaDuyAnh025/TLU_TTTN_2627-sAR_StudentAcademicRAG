"""Truy xuất dense: embed câu hỏi (OpenAI + cache) rồi query_points trên dense_small."""
from __future__ import annotations

from rag.embedding.openai_embedder import OpenAIEmbedder
from rag.embedding.qdrant_store import DENSE


class QueryEmbedder:
    """Embed câu hỏi qua OpenAIEmbedder (cache SQLite: câu hỏi lặp lại không tốn tiền)."""

    def __init__(self, cfg: dict, model: str = "small") -> None:
        self.emb, self.model = OpenAIEmbedder(cfg, model), model

    def embed(self, text: str) -> list[float]:
        plan = self.emb.plan([text])
        if plan["n_missing"]:
            self.emb.embed_missing(plan, progress=lambda *_: None)
        return self.emb.get_vectors([text])[0].tolist()


def search_dense(client, collection: str, vector: list[float], flt, k: int, model: str = "small"):
    return client.query_points(collection, query=vector, using=DENSE[model][0], query_filter=flt, limit=k, with_payload=True).points

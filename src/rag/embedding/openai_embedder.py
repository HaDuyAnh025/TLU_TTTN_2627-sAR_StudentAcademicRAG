"""Embedding OpenAI: cache SQLite theo khóa sha256(model + "\\n" + embed_text), chia batch theo số input và token,
dry-run mặc định, xử lý 429 (rate limit -> backoff + jitter; hết quota -> dừng ngay), ghi usage từng request.

Cache: 1 file SQLite mỗi mô hình, data/cache/embeddings/<model>/cache.sqlite, bảng emb(key PK, dim, vec float32 BLOB).
Không bao giờ in/ghi khóa API.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import time
from pathlib import Path

import numpy as np

QUOTA_MARKERS = ("insufficient_quota", "credit_balance_exhausted")


class QuotaExhausted(RuntimeError):
    """Hết quota/credit: dừng ngay, không retry."""


class OverBudget(RuntimeError):
    """Chi phí ước tính vượt max_cost_usd."""


def cache_key(model_name: str, text: str) -> str:
    return hashlib.sha256((model_name + "\n" + text).encode("utf-8")).hexdigest()


def count_tokens(texts: list[str]) -> list[int]:
    from rag.config import chunking_config
    chunking_config()  # đặt TIKTOKEN_CACHE_DIR (chạy offline sau lần tải đầu)
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return [len(enc.encode(t, disallowed_special=())) for t in texts]


def make_batches(items: list[tuple[str, int]], batch_size: int, max_tokens: int) -> list[list[tuple[str, int]]]:
    """Chia [(text, n_tokens)] thành các batch có <= batch_size input và tổng token <= max_tokens (input quá lớn nằm riêng một batch)."""
    out, cur, cur_tok = [], [], 0
    for it in items:
        if cur and (len(cur) >= batch_size or cur_tok + it[1] > max_tokens):
            out.append(cur)
            cur, cur_tok = [], 0
        cur.append(it)
        cur_tok += it[1]
    if cur:
        out.append(cur)
    return out


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS emb(key TEXT PRIMARY KEY, dim INTEGER NOT NULL, vec BLOB NOT NULL)")
        self.db.commit()

    def has_many(self, keys: list[str]) -> set[str]:
        found: set[str] = set()
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            q = ",".join("?" * len(part))
            found |= {r[0] for r in self.db.execute(f"SELECT key FROM emb WHERE key IN ({q})", part)}
        return found

    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            q = ",".join("?" * len(part))
            for k, blob in self.db.execute(f"SELECT key, vec FROM emb WHERE key IN ({q})", part):
                out[k] = np.frombuffer(blob, dtype=np.float32)
        return out

    def put_many(self, items: dict[str, np.ndarray]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO emb(key, dim, vec) VALUES (?,?,?)",
                            [(k, int(v.shape[0]), np.asarray(v, dtype=np.float32).tobytes()) for k, v in items.items()])
        self.db.commit()

    def close(self) -> None:
        self.db.close()


def is_quota_error(e: Exception) -> bool:
    parts = [str(getattr(e, "code", "")), str(getattr(e, "body", "")), str(e)]
    return any(m in p for p in parts for m in QUOTA_MARKERS)


class OpenAIEmbedder:
    def __init__(self, cfg: dict, model: str = "small", client=None, sleep=time.sleep, max_retries: int = 8) -> None:
        self.cfg, self.key = cfg, model
        m = cfg["openai"]["models"][model]
        self.name, self.dim = m["name"], m["dim"]
        self.price = (cfg["openai"].get("price_per_1m_tokens") or {}).get(model)
        self.batch_size = cfg["openai"]["batch_size"]
        self.max_tokens = cfg["openai"]["max_tokens_per_request"]
        self.max_cost = cfg["openai"].get("max_cost_usd")
        self.cache = EmbeddingCache(Path(cfg["cache_dir"]) / self.name / "cache.sqlite")
        self.usage_log = Path(cfg["usage_log"])
        self._client, self._sleep, self.max_retries = client, sleep, max_retries

    # ---- kế hoạch (dry-run) ----
    def plan(self, texts: list[str], assume_done: set[str] | None = None) -> dict:
        """Số chunk, số text duy nhất chưa có trong cache, token cần gọi, chi phí ước tính. KHÔNG gọi API.
        assume_done: các khóa coi như đã có (dùng khi gộp nhiều cấu hình)."""
        keys = [cache_key(self.name, t) for t in texts]
        uniq: dict[str, str] = {}
        for k, t in zip(keys, texts):
            uniq.setdefault(k, t)
        have = self.cache.has_many(list(uniq)) | (assume_done or set())
        missing = [(k, t) for k, t in uniq.items() if k not in have]
        toks = count_tokens([t for _, t in missing]) if missing else []
        total = sum(toks)
        cost = None if self.price is None else total / 1e6 * self.price
        return {"model": self.name, "n_chunks": len(texts), "n_unique": len(uniq), "n_cached": len(uniq) - len(missing),
                "n_missing": len(missing), "tokens": total, "cost_usd": cost, "price_per_1m": self.price,
                "_missing": missing, "_tokens": toks, "_keys": set(uniq)}

    # ---- gọi API ----
    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            from rag.ingestion.vlm_ocr import _load_env
            _load_env()
            if not os.environ.get("OPENAI_API_KEY"):
                raise SystemExit("Thiếu OPENAI_API_KEY (đặt trong .env)")
            self._client = OpenAI(max_retries=0)  # tự retry để kiểm soát 429
        return self._client

    def _call(self, batch_texts: list[str]):
        import openai
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.time()
                resp = self._get_client().embeddings.create(model=self.name, input=batch_texts)
                return resp, time.time() - t0
            except openai.RateLimitError as e:
                if is_quota_error(e):
                    raise QuotaExhausted(f"{type(e).__name__}: hết quota/credit OpenAI") from None
                if attempt == self.max_retries:
                    raise
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError):
                if attempt == self.max_retries:
                    raise
            self._sleep(min(60.0, 2.0 ** attempt) * (0.5 + random.random()))  # backoff có jitter

    def _log_usage(self, n_inputs: int, prompt_tokens, secs: float) -> None:
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": self.name, "n_inputs": n_inputs,
                                "prompt_tokens": prompt_tokens, "seconds": round(secs, 2)}, ensure_ascii=False) + "\n")

    def embed_missing(self, plan: dict, progress=print) -> dict:
        """Gọi API cho phần chưa có cache (ghi cache sau từng batch). Vượt max_cost_usd -> OverBudget trước khi gọi."""
        if self.max_cost is not None and plan["cost_usd"] is not None and plan["cost_usd"] > self.max_cost:
            raise OverBudget(f"Chi phí ước tính {plan['cost_usd']:.4f} USD > max_cost_usd={self.max_cost}")
        items = [(t, n) for (_, t), n in zip(plan["_missing"], plan["_tokens"])]
        done_inputs, done_tokens = 0, 0
        for batch in make_batches(items, self.batch_size, self.max_tokens):
            texts = [t for t, _ in batch]
            try:
                resp, secs = self._call(texts)
            except QuotaExhausted:
                progress(f"!! HẾT QUOTA: đã embed {done_inputs}/{len(items)} text ({done_tokens} token), đã lưu cache. "
                         f"Nạp thêm credit rồi chạy lại đúng lệnh cũ để chạy tiếp (chỉ gọi phần còn thiếu).")
                raise
            data = sorted(resp.data, key=lambda d: d.index)
            if len(data) != len(texts):
                raise RuntimeError(f"API trả {len(data)} vector cho {len(texts)} input")
            vecs = {}
            for t, d in zip(texts, data):
                v = np.asarray(d.embedding, dtype=np.float32)
                if v.shape[0] != self.dim:
                    raise RuntimeError(f"Số chiều vector {v.shape[0]} != dim={self.dim} của {self.name}")
                vecs[cache_key(self.name, t)] = v
            self.cache.put_many(vecs)
            pt = getattr(getattr(resp, "usage", None), "prompt_tokens", None)
            self._log_usage(len(texts), pt, secs)
            done_inputs += len(texts)
            done_tokens += pt or 0
            progress(f"  embed {done_inputs}/{len(items)} text, {done_tokens} token")
        return {"embedded": done_inputs, "prompt_tokens": done_tokens}

    def get_vectors(self, texts: list[str], missing_ok: bool = False) -> list[np.ndarray | None]:
        """Vector theo thứ tự texts, đọc từ cache. Thiếu -> KeyError (hoặc None nếu missing_ok)."""
        keys = [cache_key(self.name, t) for t in texts]
        got = self.cache.get_many(list(set(keys)))
        out = []
        for k in keys:
            if k not in got and not missing_ok:
                raise KeyError("Có text chưa được embed (chạy lại với --yes)")
            out.append(got.get(k))
        return out

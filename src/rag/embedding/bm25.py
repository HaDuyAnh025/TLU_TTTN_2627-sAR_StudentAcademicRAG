"""BM25 sparse cho tiếng Việt, dùng chung lúc index và lúc truy vấn.

Quy trình: NFC + chữ thường -> pyvi.ViTokenizer (từ ghép nối bằng "_") -> bỏ dấu câu và stopword (GIỮ số, mã học phần, mốc thời gian)
-> token id = 4 byte đầu của blake2b(token) (uint32, không cần từ điển) -> giá trị = TF bão hòa BM25.
IDF do Qdrant áp (modifier=IDF); phía truy vấn mỗi term có giá trị 1.0.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from rag.retrieval.normalize import domain_tokens

_EDGE = " \t\n.,;:!?()[]{}\"'“”‘’…–—-/\\|*#<>=+~`^_"
_ALNUM = re.compile(r"[0-9A-Za-zÀ-ỹ]")
_DATE = re.compile(r"(?<!\d)\d{1,2}/\d{1,2}/\d{2,4}(?!\d)")
_vi = None


def _tokenizer():
    global _vi
    if _vi is None:
        from pyvi import ViTokenizer
        _vi = ViTokenizer
    return _vi


def load_stopwords(path: Path | None) -> frozenset[str]:
    if path is None or not Path(path).exists():
        return frozenset()
    out = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        w = unicodedata.normalize("NFC", line.strip()).lower()
        if w and not w.startswith("#"):
            out.add(w)
    return frozenset(out)


def tokenize(text: str, stopwords: frozenset[str] = frozenset()) -> list[str]:
    """NFC + lower -> pyvi -> bỏ dấu câu/stopword. Số (4,0 | 650.000), mã học phần (ae321), ngày (25/3/2025) được giữ nguyên."""
    text = unicodedata.normalize("NFC", text).lower()
    out = []
    for tok in _tokenizer().tokenize(text).split():
        tok = tok.strip(_EDGE)
        if tok and _ALNUM.search(tok) and tok not in stopwords:
            out.append(tok)
    out += _DATE.findall(text)  # pyvi tách 25/3/2025 thành 25, 3, 2025: thêm nguyên mốc ngày làm một term nữa
    out += domain_tokens(text)  # học kỳ -> hk1.., năm học -> nh_2025_2026, khóa -> khoa_38 (dùng chung với query_parser)
    return out


@lru_cache(maxsize=500_000)
def token_id(token: str) -> int:
    """4 byte đầu của blake2b(token) -> uint32 (big-endian). Tái lập được, không cần từ điển."""
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8")).digest()[:4], "big")


def bm25_tf(tf: float, dl: float, avgdl: float, k1: float, b: float) -> float:
    """TF bão hòa BM25: tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))."""
    return tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))


class CollisionTracker:
    """Ghi nhận các token khác nhau cùng token id (va chạm hash) trên toàn corpus."""

    def __init__(self) -> None:
        self.by_id: dict[int, set[str]] = {}

    def add(self, tokens) -> None:
        for t in set(tokens):
            self.by_id.setdefault(token_id(t), set()).add(t)

    def report(self) -> dict:
        col = [sorted(s) for s in self.by_id.values() if len(s) > 1]
        return {"n_terms": sum(len(s) for s in self.by_id.values()), "n_ids": len(self.by_id),
                "n_collisions": len(col), "examples": col[:10]}


def doc_to_sparse(tokens: list[str], avgdl: float, k1: float, b: float) -> tuple[list[int], list[float]]:
    """(indices, values) của một văn bản; token trùng id (va chạm) được cộng dồn tần suất trước khi bão hòa."""
    dl = len(tokens)
    tf: Counter[int] = Counter(token_id(t) for t in tokens)
    idx = sorted(tf)
    return idx, [bm25_tf(tf[i], dl, avgdl, k1, b) for i in idx]


@lru_cache(maxsize=1)
def default_stopwords() -> frozenset[str]:
    from rag.embedding.settings import embedding_config
    return load_stopwords(embedding_config()["bm25"]["stopwords"])


def query_to_sparse(text: str, stopwords: frozenset[str] | None = None):
    """Sparse vector truy vấn: giá trị 1.0 cho mỗi term (IDF do Qdrant áp). Trả qdrant_client.models.SparseVector."""
    from qdrant_client import models
    sw = default_stopwords() if stopwords is None else stopwords
    idx = sorted({token_id(t) for t in tokenize(text, sw)})
    return models.SparseVector(indices=idx, values=[1.0] * len(idx))

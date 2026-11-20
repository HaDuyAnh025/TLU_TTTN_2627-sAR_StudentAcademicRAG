"""Nạp configs/embedding.yaml (đường dẫn đổi thành tuyệt đối)."""
from rag.config import ROOT, load_config


def embedding_config() -> dict:
    """Đọc configs/embedding.yaml; các đường dẫn (cache_dir, usage_log, chunks, parents, stopwords...) đổi thành tuyệt đối."""
    cfg = load_config("embedding")
    for k in ("cache_dir", "usage_log", "c3_parents"):
        cfg[k] = ROOT / cfg[k]
    cfg["chunks"] = {k: ROOT / v for k, v in cfg["chunks"].items()}
    cfg["qdrant"]["parents_path"] = ROOT / cfg["qdrant"]["parents_path"]
    cfg["bm25"]["stopwords"] = ROOT / cfg["bm25"]["stopwords"]
    cfg["bm25"]["stats_path"] = ROOT / cfg["bm25"]["stats_path"]
    return cfg

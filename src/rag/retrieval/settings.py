"""Nạp configs/retrieval.yaml (đường dẫn đổi thành tuyệt đối)."""
from rag.config import ROOT, load_config


def retrieval_config() -> dict:
    cfg = load_config("retrieval")
    cfg["hf_cache_dir"] = ROOT / cfg["hf_cache_dir"]
    return cfg

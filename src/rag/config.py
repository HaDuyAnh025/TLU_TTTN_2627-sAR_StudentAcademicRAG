"""Nạp cấu hình từ thư mục configs/ và định nghĩa các đường dẫn dữ liệu."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EVAL_DIR = DATA_DIR / "eval"


def load_config(name: str) -> dict:
    """Đọc configs/<name>.yaml (name không kèm đuôi)."""
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def chunking_config() -> dict:
    """Đọc configs/chunking.yaml; đổi đường dẫn tương đối thành tuyệt đối và đặt TIKTOKEN_CACHE_DIR."""
    import os

    cfg = load_config("chunking")
    cfg["tiktoken_cache_dir"] = str(ROOT / cfg["tiktoken_cache_dir"])
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", cfg["tiktoken_cache_dir"])
    cfg["paths"] = {k: ROOT / v for k, v in cfg["paths"].items()}
    return cfg

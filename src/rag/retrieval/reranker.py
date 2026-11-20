"""Rerank bằng BAAI/bge-reranker-v2-m3 trên CPU; nạp một lần (singleton); cache model ở data/cache/hf/.

Hai backend cùng giao diện:
  - "torch": AutoModelForSequenceClassification (cùng trọng số với CrossEncoder; điểm = sigmoid(logit)).
  - "onnx":  onnxruntime + tệp ONNX (int8 động) ở data/cache/hf/onnx/ (xem onnx_export.py).
`score_logits` trả logit thô (trước sigmoid); `score` = sigmoid(logit). Các cặp được sắp theo độ dài để giảm padding.
"""
from __future__ import annotations

import math
import os
import threading
from contextlib import nullcontext
from pathlib import Path

_lock = threading.Lock()
_instance = None


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


def _notice_if_download(model: str, cache_dir) -> None:
    """Báo tên model và dung lượng TRƯỚC khi tải lần đầu (best-effort)."""
    try:
        from huggingface_hub import try_to_load_from_cache
        if isinstance(try_to_load_from_cache(model, "config.json", cache_dir=str(cache_dir)), str):
            return
    except Exception:  # noqa: BLE001
        pass
    size = "không rõ"
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(model, files_metadata=True)
        total = sum(s.size or 0 for s in info.siblings if s.rfilename.endswith((".safetensors", ".json", ".model", ".txt")))
        size = f"~{total / 1e9:.2f} GB (safetensors + tokenizer)"
    except Exception:  # noqa: BLE001
        pass
    print(f"[reranker] Lần đầu: tải mô hình {model} từ Hugging Face, dung lượng {size}, lưu ở {cache_dir}", flush=True)


class Reranker:
    """Cơ sở: tokenizer + chia batch theo độ dài. Lớp con cài `_forward(enc) -> list[float]` (logit)."""

    def __init__(self, model: str, max_length: int = 512, batch_size: int = 16, cache_dir=None, threads: int | None = None) -> None:
        os.environ.setdefault("HF_HOME", str(cache_dir))
        _notice_if_download(model, cache_dir)
        from transformers import AutoTokenizer
        self.model_name, self.max_length, self.batch_size, self.threads = model, max_length, batch_size, threads
        self.tok = AutoTokenizer.from_pretrained(model, cache_dir=str(cache_dir))

    def _forward(self, enc) -> list[float]:
        raise NotImplementedError

    def score_logits(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        lens = [len(self.tok(query, t, truncation="longest_first", max_length=self.max_length)["input_ids"]) for t in texts]
        order = sorted(range(len(texts)), key=lambda i: -lens[i])
        out = [0.0] * len(texts)
        for s in range(0, len(order), self.batch_size):
            idx = order[s:s + self.batch_size]
            enc = self.tok([query] * len(idx), [texts[i] for i in idx], truncation="longest_first", max_length=self.max_length,
                           padding=True, return_tensors=self._tensors)
            for i, v in zip(idx, self._forward(enc)):
                out[i] = float(v)
        return out

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [sigmoid(x) for x in self.score_logits(query, texts)]


class TorchReranker(Reranker):
    _tensors = "pt"

    def __init__(self, model, max_length=512, batch_size=16, cache_dir=None, threads=None, grad_mode: str = "inference_mode") -> None:
        super().__init__(model, max_length, batch_size, cache_dir, threads)
        import torch
        from transformers import AutoModelForSequenceClassification
        if threads:
            torch.set_num_threads(threads)
        self.torch, self.grad_mode = torch, grad_mode  # inference_mode | no_grad
        self.model = AutoModelForSequenceClassification.from_pretrained(model, cache_dir=str(cache_dir)).eval()

    def _forward(self, enc) -> list[float]:
        ctx = self.torch.inference_mode() if self.grad_mode == "inference_mode" else self.torch.no_grad()
        with ctx:
            return self.model(**enc).logits.reshape(-1).float().tolist()


class OnnxReranker(Reranker):
    _tensors = "np"

    def __init__(self, model, max_length=512, batch_size=16, cache_dir=None, threads=None, onnx_path: str | Path | None = None) -> None:
        super().__init__(model, max_length, batch_size, cache_dir, threads)
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def _forward(self, enc) -> list[float]:
        import numpy as np
        feed = {k: np.asarray(enc[k], dtype=np.int64) for k in ("input_ids", "attention_mask") if k in self.inputs}
        return self.sess.run(["logits"], feed)[0].reshape(-1).astype("float32").tolist()


def make_reranker(rcfg: dict, **over) -> Reranker:
    """Dựng reranker từ configs/retrieval.yaml (mục reranker) + ghi đè (backend, max_length, threads, ...)."""
    r = {**rcfg["reranker"], **over}
    common = dict(max_length=r.get("max_length", 512), batch_size=r.get("batch_size", 16), cache_dir=rcfg["hf_cache_dir"], threads=r.get("threads"))
    if r.get("backend", "torch") == "onnx":
        path = r.get("onnx_path") or Path(rcfg["hf_cache_dir"]) / "onnx" / "bge-reranker-v2-m3-int8.onnx"
        return OnnxReranker(r["model"], onnx_path=path, **common)
    return TorchReranker(r["model"], grad_mode=r.get("grad_mode", "inference_mode"), **common)


def get_reranker(rcfg: dict) -> Reranker:
    global _instance
    with _lock:
        if _instance is None:
            _instance = make_reranker(rcfg)
        return _instance

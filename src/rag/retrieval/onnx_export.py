"""Xuất bge-reranker-v2-m3 sang ONNX rồi lượng tử hóa động int8, KHÔNG dùng optimum.

Lý do: `optimum[onnxruntime]` kéo transformers 5.x xuống 4.57 và huggingface_hub 1.x xuống 0.36 trong môi trường dùng chung;
đường này chỉ cần torch + onnx + onnxruntime (đã có) nên không đổi phiên bản gói nào khác.
Đầu ra: data/cache/hf/onnx/bge-reranker-v2-m3-int8.onnx (nặng MatMul int8; embedding giữ fp32). Tệp fp32 trung gian được xóa sau khi lượng tử hóa.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def export_int8(model_name: str, cache_dir: Path, out_dir: Path | None = None, keep_fp32: bool = False) -> Path:
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    out_dir = Path(out_dir or Path(cache_dir) / "onnx")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Bộ xuất ONNX (C++) không mở được đường dẫn có ký tự Unicode trên Windows (repo nằm trong "Thực Tập"): làm việc ở thư mục tạm ASCII.
    work = Path(tempfile.mkdtemp(prefix="onnx_rerank_"))
    tmp, qdir = work / "fp32", work / "int8"
    tmp.mkdir()
    qdir.mkdir()
    fp32, int8 = tmp / "model.onnx", qdir / "bge-reranker-v2-m3-int8.onnx"
    tok = AutoTokenizer.from_pretrained(model_name, cache_dir=str(cache_dir))
    model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=str(cache_dir)).eval()

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):
            return self.m(input_ids=input_ids, attention_mask=attention_mask).logits

    enc = tok(["câu hỏi mẫu", "học phí"], ["đoạn văn mẫu dài hơn một chút để có độ dài khác nhau " * 3, "ngắn"], padding=True, return_tensors="pt")
    with torch.inference_mode():
        torch.onnx.export(Wrap(model), (enc["input_ids"], enc["attention_mask"]), str(fp32), input_names=["input_ids", "attention_mask"],
                          output_names=["logits"], dynamic_axes={"input_ids": {0: "batch", 1: "seq"}, "attention_mask": {0: "batch", 1: "seq"},
                                                                "logits": {0: "batch"}}, opset_version=17, dynamo=False)
    del model
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8, use_external_data_format=True)
    for f in qdir.iterdir():
        shutil.move(str(f), str(out_dir / f.name))
    if not keep_fp32:
        shutil.rmtree(work, ignore_errors=True)
    return out_dir / int8.name

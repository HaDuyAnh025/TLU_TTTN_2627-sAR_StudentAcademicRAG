"""(TÙY CHỌN, tách riêng) VLM đọc lại các trang scan bị gắn cờ.

Quan trọng — tuân thủ nguyên tắc "không suy diễn, không sửa kết quả":
  - KHÔNG ghi đè hay chỉnh bất cứ thứ gì trong data/interim/extract.
  - Kết quả VLM (do mô hình SINH văn bản) được lưu riêng ở data/interim/vlm/<id>.json, gắn nhãn model,
    mã băm prompt, và tham chiếu tới trang gốc. Bước sau muốn dùng hay không là quyết định của người dùng.
  - Không có đường nhập đáp án tay.
  - Không chạy nếu chưa có khóa API; chỉ liệt kê các trang bị gắn cờ.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from datetime import datetime
from pathlib import Path

from rag.config import ROOT, load_config
from rag.ingestion.loader import FILES_DIR, number_mismatch, out_dir, split_markdown_blocks
from rag.ingestion.ocr_engines import load_image_file, render_pdf_page

TRIGGER_FLAGS = {"low_dpi", "low_conf", "low_text", "garbled", "table_suspected", "number_mismatch"}


def vlm_dir() -> Path:
    return ROOT / "data" / "interim" / "vlm"


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def page_id(doc: dict, pg: dict) -> str:
    stem = Path(doc["file"]).stem
    return stem if pg["page"] is None else f"{stem}-p{pg['page']}"


def render_for_vlm(doc: dict, pg: dict, dpi: int):
    path = FILES_DIR / doc["file"]
    img = load_image_file(path) if doc["file_kind"] == "image" else render_pdf_page(path, pg["page"], dpi)
    angle = pg["raw"]["orientation"]["angle_ccw"]
    return img.rotate(angle, expand=True) if angle else img


def _to_jpeg_b64(img, max_side: int) -> str:
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def transcribe_anthropic(img, vcfg: dict, prompt: str | None = None) -> tuple[str, dict]:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=vcfg["model"], max_tokens=vcfg["max_tokens"],
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": _to_jpeg_b64(img, vcfg["max_side"])}},
            {"type": "text", "text": prompt or vcfg["prompt"]},
        ]}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    usage = {"input_tokens": getattr(msg.usage, "input_tokens", None),
             "output_tokens": getattr(msg.usage, "output_tokens", None)}
    return text, usage


def transcribe_openai(img, vcfg: dict, prompt: str | None = None) -> tuple[str, dict]:
    """OpenAI (Chat Completions, ảnh gửi dạng data URL). Tên mô hình lấy từ configs/ocr.yaml: vlm.openai.model."""
    from openai import OpenAI
    oc = vcfg.get("openai") or {}
    client = OpenAI()
    url = "data:image/jpeg;base64," + _to_jpeg_b64(img, vcfg["max_side"])
    resp = client.chat.completions.create(
        model=oc["model"], max_completion_tokens=vcfg["max_tokens"],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt or vcfg["prompt"]},
            {"type": "image_url", "image_url": {"url": url, "detail": oc.get("detail", "high")}},
        ]}])
    text = (resp.choices[0].message.content or "").strip()
    u = resp.usage
    usage = {"input_tokens": getattr(u, "prompt_tokens", None), "output_tokens": getattr(u, "completion_tokens", None)}
    return text, usage


# nhà cung cấp → (biến môi trường chứa khóa, hàm gọi)
PROVIDERS = {"anthropic": ("ANTHROPIC_API_KEY", transcribe_anthropic),
             "openai": ("OPENAI_API_KEY", transcribe_openai)}


def provider_model(vcfg: dict) -> str:
    prov = vcfg["provider"]
    if prov == "openai":
        return ((vcfg.get("openai") or {}).get("model") or "").strip()
    return vcfg.get("model", "")


def model_ready(vcfg: dict) -> tuple[str, str, bool, str, object]:
    """(nhà cung cấp, mô hình, có khóa?, tên biến khóa, hàm gọi). Dùng chung cho các bước cần gọi mô hình."""
    _load_env()
    prov = vcfg["provider"]
    if prov not in PROVIDERS:
        raise SystemExit(f"Nhà cung cấp VLM không hỗ trợ: {prov} (chọn: {', '.join(PROVIDERS)})")
    env_name, fn = PROVIDERS[prov]
    return prov, provider_model(vcfg), bool(os.environ.get(env_name)), env_name, fn


def list_flagged(cfg: dict) -> list[tuple[dict, dict]]:
    out = []
    from rag.evaluation.extract_eval import load_docs  # dùng chung bộ đọc đã xử lý tên file tiếng Việt
    for doc in load_docs(cfg):
        for pg in doc["pages"]:
            if pg.get("route") == "ocr" and not pg.get("error") and TRIGGER_FLAGS & set(pg["quality"]["flags"]):
                out.append((doc, pg))
    return out


def run_vlm(cfg: dict | None = None, limit: int | None = None, dry_run: bool = False) -> dict:
    cfg = cfg or load_config("ocr")
    vcfg = cfg["vlm"]
    _load_env()
    todo = [(d, p) for d, p in list_flagged(cfg) if not (vlm_dir() / f"{page_id(d, p)}.json").exists()]
    if limit:
        todo = todo[:limit]
    from collections import Counter
    by_flag = Counter(f for _, p in todo for f in p["quality"]["flags"] if f in TRIGGER_FLAGS)
    est_in = len(todo) * 1750  # giả định chung ~1.500 token ảnh + ~250 token chỉ dẫn; mỗi nhà cung cấp tính ảnh khác nhau
    print(f"{len(todo)} trang scan bị gắn cờ chưa có kết quả VLM. Theo cờ: {dict(by_flag)}")
    print(f"Ước tính thô ~{est_in:,} token vào (1.750/trang) và ~{len(todo) * 800:,}-{len(todo) * 1000:,} token ra; "
          "chưa nhân giá. Số thật khác tùy nhà cung cấp → chạy thử --limit 20 để đo.")
    prov = vcfg["provider"]
    if prov not in PROVIDERS:
        raise SystemExit(f"Nhà cung cấp VLM không hỗ trợ: {prov} (chọn: {', '.join(PROVIDERS)})")
    env_name, transcribe = PROVIDERS[prov]
    model = provider_model(vcfg)
    has_key = bool(os.environ.get(env_name))
    print(f"Nhà cung cấp: {prov} · mô hình: {model or '(CHƯA ĐIỀN)'} · khóa {env_name}: {'có' if has_key else 'chưa có'}")
    if dry_run or not has_key or not model:
        if dry_run:
            print("Chỉ liệt kê (dry-run).")
        elif not model:
            print(f"Chưa điền tên mô hình: đặt vlm.{prov}.model trong configs/ocr.yaml → không gọi VLM.")
        else:
            print(f"Chưa có {env_name} (đặt trong môi trường hoặc file .env) → không gọi VLM, không thay đổi gì.")
        return {"flagged": len(todo), "called": 0}
    vlm_dir().mkdir(parents=True, exist_ok=True)
    prompt_sha = hashlib.sha256(vcfg["prompt"].encode("utf-8")).hexdigest()
    called = errors = 0
    for n, (doc, pg) in enumerate(todo, 1):
        pid = page_id(doc, pg)
        try:
            md, usage = transcribe(render_for_vlm(doc, pg, cfg.get("render_dpi", 200)), vcfg)
            ocr_text = pg["derived"]["text"]
            ratio, examples = number_mismatch(ocr_text, md)
            rec = {"id": pid, "file": doc["file"], "page": pg["page"], "input_sha256": doc["input_sha256"],
                   "provider": prov, "model": model, "prompt_sha256": prompt_sha,
                   "generated_at": datetime.now().isoformat(timespec="seconds"), "usage": usage,
                   "output_markdown": md, "blocks": split_markdown_blocks(md),
                   "number_diff_vs_ocr": {"ratio": round(ratio, 3), "examples": examples},
                   "note": "Văn bản do mô hình sinh, KHÔNG phải kết quả OCR gốc; không ghi đè data/interim/extract."}
            (vlm_dir() / f"{pid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            called += 1
            print(f"  [{n}/{len(todo)}] {pid}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"  ! {pid}: {type(e).__name__}: {e}")
    print(f"Xong: gọi {called}, lỗi {errors}.")
    return {"flagged": len(todo), "called": called, "errors": errors}

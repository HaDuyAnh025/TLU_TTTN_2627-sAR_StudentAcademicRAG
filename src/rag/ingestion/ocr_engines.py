"""Các công cụ OCR dùng chung (benchmark hiện tại, loader.py sau này).

Mọi công cụ có cùng giao diện: engine.run(PIL.Image) -> list[Word].
Công cụ chưa cài / thiếu dữ liệu sẽ ném EngineUnavailable kèm lý do, không làm hỏng cả chương trình.
"""
from __future__ import annotations

import logging
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageOps


CPU_THREADS: int | None = None  # giới hạn số luồng CPU mỗi tiến trình (đặt qua configs/ocr.yaml: cpu_threads)


def _rapid_thread_params() -> dict:
    """Tham số RapidOCR/onnxruntime: mặc định dùng MỌI luồng máy báo (vd 80) dù container chỉ được cấp ~10 CPU → tranh nhau, rất chậm."""
    if not CPU_THREADS:
        return {}
    return {"EngineConfig.onnxruntime.intra_op_num_threads": CPU_THREADS,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1}


class EngineUnavailable(Exception):
    """Công cụ OCR không dùng được (chưa cài, thiếu model...)."""


@dataclass
class Word:
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 (pixel)
    text: str
    conf: float | None = None               # 0..1


# ---------------------------------------------------------------- ảnh đầu vào
def render_pdf_page(path: str | Path, page_index: int, dpi: int = 200) -> Image.Image:
    """Dựng một trang PDF thành ảnh. PyMuPDF đã áp dụng cờ /Rotate của trang."""
    with pymupdf.open(path) as doc:
        pix = doc[page_index].get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def load_image_file(path: str | Path) -> Image.Image:
    img = Image.open(path)
    return ImageOps.exif_transpose(img).convert("RGB")


# ----------------------------------------------------------- gộp từ thành dòng
def words_to_text(words: list[Word], gap_factor: float = 2.5) -> str:
    """Gom các từ/dòng OCR thành văn bản theo dòng; khoảng trống lớn → " | " (gợi ý cột bảng)."""
    if not words:
        return ""
    heights = sorted(max(1.0, w.box[3] - w.box[1]) for w in words)
    med = heights[len(heights) // 2]
    ordered = sorted(words, key=lambda w: (w.box[1] + w.box[3]) / 2)
    lines: list[dict] = []
    for w in ordered:
        cy = (w.box[1] + w.box[3]) / 2
        if lines and abs(cy - lines[-1]["cy"]) <= med * 0.6:
            lines[-1]["w"].append(w)
            lines[-1]["cy"] = sum((x.box[1] + x.box[3]) / 2 for x in lines[-1]["w"]) / len(lines[-1]["w"])
        else:
            lines.append({"cy": cy, "w": [w]})
    out = []
    for ln in lines:
        ws = sorted(ln["w"], key=lambda w: w.box[0])
        s = ws[0].text
        for a, b in zip(ws, ws[1:]):
            s += (" | " if b.box[0] - a.box[2] > med * gap_factor else " ") + b.text
        out.append(s)
    return "\n".join(out)


# ------------------------------------------------------------------ Tesseract
def default_tessdata_dir() -> Path:
    return Path.home() / ".sar-ocr" / "tessdata"


class TesseractEngine:
    def __init__(self, opts: dict):
        try:
            import pytesseract
        except ImportError as e:
            raise EngineUnavailable("chưa cài pytesseract (pip install pytesseract)") from e
        cmd = opts.get("cmd") or os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
        if not cmd:
            for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                      r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
                if Path(c).exists():
                    cmd = c
                    break
        if not cmd:
            raise EngineUnavailable("không tìm thấy tesseract.exe (winget install UB-Mannheim.TesseractOCR)")
        tessdata = Path(opts.get("tessdata_dir") or default_tessdata_dir())
        if tessdata.exists():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
        pytesseract.pytesseract.tesseract_cmd = cmd
        self.pt = pytesseract
        self.lang = opts.get("lang", "vie+eng")
        self.psm = opts.get("psm", 3)
        have = set(pytesseract.get_languages(config=""))
        missing = [l for l in self.lang.split("+") if l not in have]
        if missing:
            raise EngineUnavailable(
                f"thiếu dữ liệu ngôn ngữ {missing}; chạy: python scripts/ocr_benchmark.py setup")
        self.name = "tesseract"

    def run(self, img: Image.Image) -> list[Word]:
        d = self.pt.image_to_data(img, lang=self.lang, config=f"--psm {self.psm}",
                                  output_type=self.pt.Output.DICT)
        words = []
        for i, t in enumerate(d["text"]):
            t = t.strip()
            conf = float(d["conf"][i])
            if not t or conf < 0:
                continue
            x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            words.append(Word((x, y, x + w, y + h), t, conf / 100))
        return words


def setup_tessdata(variant: str = "best", dest: str | Path | None = None) -> Path:
    """Tải vie.traineddata (và eng/osd nếu thiếu) vào thư mục người dùng, không cần quyền admin."""
    dest = Path(dest or default_tessdata_dir())
    dest.mkdir(parents=True, exist_ok=True)
    installed = Path(r"C:\Program Files\Tesseract-OCR\tessdata")
    for name in ("eng", "osd", "vie"):
        target = dest / f"{name}.traineddata"
        if target.exists() and target.stat().st_size > 10_000:
            continue
        src = installed / f"{name}.traineddata"
        if name != "vie" and src.exists():
            shutil.copy(src, target)
            continue
        url = f"https://github.com/tesseract-ocr/tessdata_{variant}/raw/main/{name}.traineddata"
        print(f"  tải {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "sAR-ocr-setup/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r, target.open("wb") as f:
            shutil.copyfileobj(r, f)
    return dest


# ------------------------------------------------------------------- RapidOCR
class RapidOcrEngine:
    VERSIONS = {"ppocrv5": "PPOCRV5", "ppocrv4": "PPOCRV4"}

    def __init__(self, opts: dict, version: str = "ppocrv5"):
        try:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        except ImportError as e:
            raise EngineUnavailable("chưa cài rapidocr (pip install rapidocr onnxruntime)") from e
        if version not in self.VERSIONS:
            raise EngineUnavailable(f"phiên bản rapidocr không hợp lệ: {version}")
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        self.ocr = RapidOCR(params={
            "Rec.lang_type": LangRec.LATIN,
            "Rec.ocr_version": getattr(OCRVersion, self.VERSIONS[version]),
            "Rec.model_type": ModelType.MOBILE,
            **_rapid_thread_params(),
        })
        self.name = f"rapidocr:{version}"

    def run(self, img: Image.Image) -> list[Word]:
        out = self.ocr(np.array(img.convert("RGB")))
        if out is None or out.txts is None:
            return []
        words = []
        for box, text, score in zip(out.boxes, out.txts, out.scores):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append(Word((min(xs), min(ys), max(xs), max(ys)), text, float(score)))
        return words


# --------------------------------------------------------------------- EasyOCR
class EasyOcrEngine:
    def __init__(self, opts: dict):
        try:
            import easyocr
        except ImportError as e:
            raise EngineUnavailable("chưa cài easyocr (pip install easyocr)") from e
        self.reader = easyocr.Reader(opts.get("langs", ["vi", "en"]), gpu=opts.get("gpu", False), verbose=False)
        self.name = "easyocr"

    def run(self, img: Image.Image) -> list[Word]:
        words = []
        for box, text, conf in self.reader.readtext(np.array(img.convert("RGB"))):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append(Word((min(xs), min(ys), max(xs), max(ys)), text, float(conf)))
        return words


# ------------------------------------------------- PP-OCR detect + VietOCR rec
class VietOcrEngine:
    """Dò dòng chữ bằng bộ dò PP-OCR (chạy qua RapidOCR/ONNX, không cần PaddlePaddle),
    rồi nhận dạng từng dòng bằng VietOCR (mô hình riêng cho tiếng Việt)."""

    def __init__(self, opts: dict, model: str = "vgg_transformer"):
        try:
            from rapidocr import RapidOCR
            from vietocr.tool.config import Cfg
            from vietocr.tool.predictor import Predictor
        except ImportError as e:
            raise EngineUnavailable(f"thiếu thư viện ({e.name}); pip install vietocr --no-deps einops gdown torchvision") from e
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        self.det = RapidOCR(params={"Global.use_cls": False, "Global.use_rec": False, **_rapid_thread_params()})
        cfg = Cfg.load_config_from_name(model)
        dev = opts.get("device", "auto")
        if dev == "auto":
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        cfg["device"] = dev
        cfg["predictor"]["beamsearch"] = False
        self.pred = Predictor(cfg)
        self.batch = opts.get("batch_size", 32)
        self.pad = opts.get("pad", 3)
        self.name = f"vietocr:{model}"

    def run(self, img: Image.Image) -> list[Word]:
        img = img.convert("RGB")
        out = self.det(np.array(img))
        if out is None or out.boxes is None:
            return []
        crops, boxes = [], []
        for b in out.boxes:
            xs = [p[0] for p in b]
            ys = [p[1] for p in b]
            x0, y0 = max(0, min(xs) - self.pad), max(0, min(ys) - self.pad)
            x1, y1 = min(img.width, max(xs) + self.pad), min(img.height, max(ys) + self.pad)
            if y1 - y0 < 8 or x1 - x0 < 8:
                continue
            crops.append(img.crop((int(x0), int(y0), int(x1), int(y1))))
            boxes.append((x0, y0, x1, y1))
        words: list[Word] = []
        for i in range(0, len(crops), self.batch):
            chunk = crops[i:i + self.batch]
            res = self.pred.predict_batch(chunk, return_prob=True)
            texts, probs = res if isinstance(res, tuple) else (res, [None] * len(chunk))
            for box, t, p in zip(boxes[i:i + self.batch], texts, probs):
                if t and t.strip():
                    words.append(Word(box, t.strip(), None if p is None else float(p)))
        return words


# ----------------------------------------------------------- PaddleOCR-VL (VLM nhỏ)
class PaddleOcrVlEngine:
    """PaddleOCR-VL (~0.9B tham số) qua transformers. Đọc cả trang, trả về Markdown trong MỘT Word.
    Cần GPU NVIDIA để chạy thực tế (trên CPU mất hàng chục phút mỗi trang)."""

    def __init__(self, opts: dict):
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as e:
            raise EngineUnavailable(f"thiếu thư viện ({e.name}); pip install transformers torch") from e
        dev = opts.get("device", "auto")
        if dev == "auto":
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        if dev == "cpu" and not opts.get("allow_cpu", False):
            raise EngineUnavailable("paddleocr_vl cần GPU (đặt paddleocr_vl.allow_cpu: true để ép chạy CPU, rất chậm)")
        self.torch = torch
        name = opts.get("model", "PaddlePaddle/PaddleOCR-VL")
        dtype = torch.bfloat16 if dev == "cuda" else torch.float32
        self.model = AutoModelForImageTextToText.from_pretrained(name, dtype=dtype).to(dev).eval()
        self.proc = AutoProcessor.from_pretrained(name)
        self.prompt = opts.get("prompt", "OCR:")
        self.max_new = int(opts.get("max_new_tokens", 2048))
        self.name = "paddleocr_vl"

    def run(self, img: Image.Image) -> list[Word]:
        msgs = [{"role": "user", "content": [{"type": "image", "image": img.convert("RGB")},
                                             {"type": "text", "text": self.prompt}]}]
        inputs = self.proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True,
                                               return_dict=True, return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=self.max_new)
        text = self.proc.decode(out[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True).strip()
        return [Word((0, 0, img.width, img.height), text, None)] if text else []


# ---------------------------------------------------------------- khởi tạo chung
def build_engines(specs: list[str], cfg: dict) -> tuple[dict, dict]:
    """Trả về (engine_dùng_được, {tên: lý_do_không_dùng_được})."""
    global CPU_THREADS
    CPU_THREADS = cfg.get("cpu_threads") or None
    if CPU_THREADS:
        os.environ.setdefault("OMP_NUM_THREADS", str(CPU_THREADS))
        try:
            import torch
            torch.set_num_threads(int(CPU_THREADS))
        except ImportError:
            pass
    ok: dict = {}
    bad: dict = {}
    for spec in specs:
        base, _, variant = spec.partition(":")
        try:
            if base == "tesseract":
                eng = TesseractEngine(cfg.get("tesseract", {}))
            elif base == "rapidocr":
                eng = RapidOcrEngine(cfg.get("rapidocr", {}), variant or "ppocrv5")
            elif base == "vietocr":
                eng = VietOcrEngine(cfg.get("vietocr", {}), variant or "vgg_transformer")
            elif base == "paddleocr_vl":
                eng = PaddleOcrVlEngine(cfg.get("paddleocr_vl", {}))
            elif base == "easyocr":
                eng = EasyOcrEngine(cfg.get("easyocr", {}))
            else:
                raise EngineUnavailable(f"không biết công cụ '{spec}'")
            ok[spec] = eng
        except EngineUnavailable as e:
            bad[spec] = str(e)
        except Exception as e:  # noqa: BLE001
            bad[spec] = f"{type(e).__name__}: {e}"
    return ok, bad


# --------------------------------------------------------------- dò hướng ảnh
def _score(words: list[Word]) -> float:
    return sum(len(w.text) * (w.conf or 0) for w in words if (w.conf or 0) >= 0.5)


def detect_rotation(img: Image.Image, engine, max_side: int = 1400, return_scores: bool = False):
    """Thử xoay 0/90/180/270 (ngược chiều kim đồng hồ), chọn góc cho điểm OCR cao nhất.

    Dừng sớm nếu ảnh gốc đã đọc tốt. Chỉ đổi hướng khi điểm tốt hơn rõ rệt (>1,3 lần).
    return_scores=True → trả về (góc, {góc: điểm}) để ghi lại bằng chứng quyết định.
    """
    small = img.copy()
    small.thumbnail((max_side, max_side))
    scores: dict[int, float] = {}
    for angle in (0, 90, 180, 270):
        im = small if angle == 0 else small.rotate(angle, expand=True)
        words = engine.run(im)
        scores[angle] = _score(words)
        if angle == 0 and len(words) >= 15:
            mean_conf = sum(w.conf or 0 for w in words) / len(words)
            if mean_conf >= 0.85:
                return (0, scores) if return_scores else 0
    best = max(scores, key=scores.get)
    angle = best if scores[best] > 1.3 * max(scores[0], 1.0) else 0
    return (angle, scores) if return_scores else angle

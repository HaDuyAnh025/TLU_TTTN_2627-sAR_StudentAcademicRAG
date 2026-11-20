"""Trích xuất text + OCR toàn bộ file trong data/raw/files (PDF, ảnh) — KHÔNG suy diễn, KHÔNG sửa tay.

Nguyên tắc:
  1. Kết quả GỐC của công cụ (PyMuPDF / OCR) được lưu nguyên trong trường "raw", không bị chỉnh sửa.
  2. Mọi thứ khác ("derived", "quality") là hàm XÁC ĐỊNH của "raw" (gom dòng, bảng → Markdown, cờ chất lượng),
     nên có thể tính lại và so khớp bằng `--stage verify`. Nếu ai sửa tay kết quả, verify sẽ báo lệch.
  3. Không có bước nào gọi mô hình sinh văn bản (LLM/VLM) hay chèn đáp án tay. Cờ chất lượng chỉ là thông tin kèm theo.
  4. Lỗi không bị nuốt: trang lỗi được ghi "error" và file đó sẽ được xử lý lại ở lần chạy sau.

Mỗi file đầu vào → data/interim/extract/<tên file>.json  (schema 2). Chạy lại được, bỏ qua file đã xong và còn khớp mã băm.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime
from importlib import metadata
from pathlib import Path

import pymupdf

from rag.config import CONFIG_DIR, RAW_DIR, ROOT, load_config
from rag.ingestion.ocr_engines import (
    Word, build_engines, detect_rotation, load_image_file, render_pdf_page, words_to_text,
)

SCHEMA = 2
FILES_DIR = RAW_DIR / "files"
NUM_RE = re.compile(r"\d+(?:[.,/:\-]\d+)*")
IMG_EXT = (".jpg", ".jpeg", ".png")
NL = chr(10)


def out_dir(cfg: dict) -> Path:
    return ROOT / cfg["pipeline"]["out_dir"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------- bảng / markdown
def table_to_markdown(rows: list[list]) -> str:
    rows = [[("" if c is None else re.sub(r"\s+", " ", str(c)).strip()) for c in r] for r in rows if r]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return NL.join(lines)


def split_markdown_blocks(md: str) -> list[dict]:
    """Tách Markdown thành block: các dòng liên tiếp bắt đầu bằng '|' → table, còn lại → text."""
    blocks, buf, is_tbl = [], [], False

    def flush():
        nonlocal buf
        content = NL.join(buf).strip()
        if content:
            blocks.append({"type": "table" if is_tbl else "text", "content": content})
        buf = []

    for line in md.splitlines():
        t = line.strip().startswith("|")
        if buf and t != is_tbl:
            flush()
        is_tbl = t
        buf.append(line)
    flush()
    return blocks


# ------------------------------------------------------------------- số liệu / cờ
def _numbers(text: str) -> Counter:
    """Chuỗi số có ≥3 ký tự (bỏ số thứ tự 1-2 chữ số, vốn dễ nhiễu)."""
    return Counter(t for t in NUM_RE.findall(text) if len(t) >= 3)


def number_mismatch(a: str, b: str) -> tuple[float, list[str]]:
    na, nb = _numbers(a), _numbers(b)
    union = sum((na | nb).values())
    if not union:
        return 0.0, []
    diff = (na - nb) + (nb - na)
    return sum(diff.values()) / union, [k for k, _ in diff.most_common(8)]


def garble_ratio(text: str) -> float:
    if not text:
        return 1.0
    ok = sum(1 for c in text if c.isalnum() or c.isspace() or c in ".,;:()/-–—%\"'|+&")
    return 1 - ok / len(text)


def compute_flags(info: dict, text: str, cross_text: str | None, fcfg: dict) -> tuple[list[str], dict]:
    flags: list[str] = []
    detail: dict = {}
    if info["dpi"] and info["dpi"] < fcfg["min_dpi"]:
        flags.append("low_dpi")
        detail["dpi"] = info["dpi"]
    if info.get("mean_conf") is not None and info["mean_conf"] < fcfg["min_mean_conf"]:
        flags.append("low_conf")
        detail["mean_conf"] = round(info["mean_conf"], 3)
    if len(text.strip()) < fcfg["min_chars_scan"]:
        flags.append("low_text")
    if garble_ratio(text) > fcfg["garble_ratio"]:
        flags.append("garbled")
    gap_lines = sum(1 for ln in text.splitlines() if " | " in ln)
    need = fcfg["table_gap_lines_landscape"] if info.get("landscape") else fcfg["table_gap_lines"]
    if gap_lines >= need:
        flags.append("table_suspected")
        detail["gap_lines"] = gap_lines
    if cross_text is not None:
        ratio, examples = number_mismatch(text, cross_text)
        if ratio > fcfg["number_mismatch_ratio"]:
            flags.append("number_mismatch")
            detail["number_mismatch"] = {"ratio": round(ratio, 3), "examples": examples}
    return flags, detail


# ------------------------------------------------------------------- trang có lớp text
def raw_text_layer(page: "pymupdf.Page") -> dict:
    """Kết quả GỐC của PyMuPDF cho một trang."""
    blocks = [[round(b[0], 1), round(b[1], 1), round(b[2], 1), round(b[3], 1), b[4], b[5], b[6]]
              for b in page.get_text("blocks")]
    tables, table_error = [], None
    try:
        for t in page.find_tables().tables:
            tables.append({"bbox": [round(v, 1) for v in t.bbox], "rows": t.extract()})
    except Exception as e:  # noqa: BLE001
        table_error = f"{type(e).__name__}: {e}"
    return {"engine": "pymupdf", "text": page.get_text("text"), "blocks": blocks, "tables": tables,
            "table_error": table_error}


def derive_text_layer(raw: dict, page_height: float) -> tuple[dict, list[str]]:
    """Hàm xác định: raw → (derived, cờ). Bảng → Markdown, text trùng vùng bảng bị bỏ, sắp theo vị trí."""
    flags: list[str] = []
    items: list[tuple[float, float, dict]] = []
    rects = []
    for t in raw["tables"]:
        md = table_to_markdown(t["rows"])
        if not md:
            continue
        r = pymupdf.Rect(t["bbox"])
        rects.append(r)
        items.append((r.y0, r.x0, {"type": "table", "content": md}))
        if r.y1 > page_height * 0.92:
            flags.append("table_maybe_continues")
        if r.y0 < page_height * 0.08:
            flags.append("table_maybe_continued")
    for b in raw["blocks"]:
        x0, y0, x1, y1, text, _no, btype = b
        if btype != 0 or not text.strip():
            continue
        r = pymupdf.Rect(x0, y0, x1, y1)
        if any((r & tr).get_area() > 0.5 * max(r.get_area(), 1e-6) for tr in rects):
            continue
        items.append((y0, x0, {"type": "text", "content": text.strip()}))
    items.sort(key=lambda x: (round(x[0]), x[1]))
    blocks = [it[2] for it in items]
    return {"text": (NL * 2).join(b["content"] for b in blocks), "blocks": blocks}, flags


# ------------------------------------------------------------------- trang OCR
def serialize_words(words: list[Word]) -> list[dict]:
    return [{"box": [round(float(v), 1) for v in w.box], "text": str(w.text),
             "conf": None if w.conf is None else round(float(w.conf), 4)} for w in words]


def deserialize_words(items: list[dict]) -> list[Word]:
    return [Word(tuple(i["box"]), i["text"], i["conf"]) for i in items]


def derive_ocr(raw: dict) -> dict:
    """Hàm xác định: các từ OCR gốc → văn bản theo dòng."""
    text = words_to_text(deserialize_words(raw["words"]))
    return {"text": text, "blocks": [{"type": "text", "content": text}] if text.strip() else []}


def quality_ocr(raw: dict, features: dict, derived: dict, fcfg: dict) -> dict:
    words = deserialize_words(raw["words"])
    confs = [w.conf for w in words if w.conf is not None]
    mean_conf = sum(confs) / len(confs) if confs else None
    cross_text = None
    if raw.get("crosscheck"):
        cross_text = words_to_text(deserialize_words(raw["crosscheck"]["words"]))
    info = {"dpi": features["dpi"], "mean_conf": mean_conf, "landscape": features["landscape"]}
    flags, detail = compute_flags(info, derived["text"], cross_text, fcfg)
    return {"flags": flags, "detail": detail, "mean_conf": None if mean_conf is None else round(mean_conf, 4)}


def quality_text_layer(raw: dict, features: dict, derived_flags: list[str], reason: str) -> dict:
    flags = list(derived_flags)
    if features["image_cov"] >= 0.5:
        flags.append("embedded_ocr_text")  # trang là ảnh scan có sẵn lớp OCR: chất lượng chưa rõ
    if reason == "it_chu_khong_phai_anh":
        flags.append("few_text")
    return {"flags": flags, "detail": {}, "mean_conf": None}


# ------------------------------------------------------------------- đặc điểm trang
def page_features(page: "pymupdf.Page") -> dict:
    chars = len(page.get_text().strip())
    cov, dpi = 0.0, 0
    for im in page.get_image_info():
        inter = pymupdf.Rect(im["bbox"]) & page.rect
        if not inter.is_empty:
            c = inter.get_area() / page.rect.get_area()
            if c > cov:
                cov = c
                span = (page.rect.width if page.rotation in (0, 180) else page.rect.height) / 72
                dpi = round(im["width"] / span) if span else 0
    return {"chars": chars, "image_cov": round(cov, 3), "dpi": dpi, "landscape": page.rect.width > page.rect.height,
            "rotation_flag": page.rotation, "height": round(page.rect.height, 1)}


def route_of(features: dict, min_chars: int) -> tuple[str, str]:
    if features["chars"] >= min_chars:
        return "text_layer", "co_lop_text"
    if features["image_cov"] >= 0.5:
        return "ocr", "anh_scan_khong_co_text"
    if features["chars"] == 0:
        return "ocr", "trang_trong_hoac_khong_co_text"
    return "text_layer", "it_chu_khong_phai_anh"


# ------------------------------------------------------------------- pipeline
class Pipeline:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config("ocr")
        pc = self.cfg["pipeline"]
        specs = [pc["base_engine"]] + ([pc["crosscheck_engine"]] if pc.get("crosscheck_engine") else [])
        engines, bad = build_engines(specs, self.cfg)
        if pc["base_engine"] not in engines:
            raise SystemExit(f"OCR nền không dùng được: {bad.get(pc['base_engine'])}")
        for k, v in bad.items():
            print(f"  ! bỏ qua {k}: {v}")
        self.base = engines[pc["base_engine"]]
        self.cross = engines.get(pc.get("crosscheck_engine"))
        self.orienter = self.cross or self.base
        ocfg = self.cfg.get("orientation", {})
        self.orient_on = ocfg.get("enabled", True)
        self.orient_side = ocfg.get("max_side", 1400)
        self.dpi = self.cfg.get("render_dpi", 200)
        self.min_chars = pc["text_layer_min_chars"]
        self.min_numbers = pc["crosscheck_min_numbers"]
        self.fcfg = self.cfg["flags"]
        self.out = out_dir(self.cfg)
        self.out.mkdir(parents=True, exist_ok=True)
        self.provenance = self._provenance()

    def _provenance(self) -> dict:
        libs = {}
        for name in ("pymupdf", "torch", "vietocr", "rapidocr", "onnxruntime", "pillow", "numpy", "transformers"):
            try:
                libs[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                pass
        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda:" + torch.cuda.get_device_name(0)
        except Exception:  # noqa: BLE001
            pass
        cfg_bytes = (CONFIG_DIR / "ocr.yaml").read_bytes()
        return {"schema": SCHEMA, "base_engine": self.base.name,
                "crosscheck_engine": self.cross.name if self.cross else None,
                "orientation": {"enabled": self.orient_on, "engine": self.orienter.name, "max_side": self.orient_side},
                "render_dpi": self.dpi, "text_layer_min_chars": self.min_chars,
                "crosscheck_min_numbers": self.min_numbers, "flag_thresholds": self.fcfg,
                "ocr_yaml_sha256": hashlib.sha256(cfg_bytes).hexdigest(), "libs": libs, "device": device}

    # ---- OCR một ảnh → raw
    def raw_ocr(self, img) -> dict:
        angle, scores = 0, {}
        if self.orient_on:
            angle, scores = detect_rotation(img, self.orienter, self.orient_side, return_scores=True)
        if angle:
            img = img.rotate(angle, expand=True)
        words = self.base.run(img)
        raw = {"engine": self.base.name, "image_size": [img.width, img.height],
               "orientation": {"method": "thu_0_90_180_270_cham_diem_ocr", "engine": self.orienter.name,
                               "angle_ccw": angle, "scores": {str(k): round(float(v), 2) for k, v in scores.items()}},
               "words": serialize_words(words), "crosscheck": None}
        text = words_to_text(words)
        if self.cross and len(NUM_RE.findall(text)) >= self.min_numbers:
            raw["crosscheck"] = {"engine": self.cross.name, "words": serialize_words(self.cross.run(img))}
        return raw

    def _ocr_entry(self, img, features: dict, entry: dict) -> dict:
        raw = self.raw_ocr(img)
        derived = derive_ocr(raw)
        entry.update(raw=raw, derived=derived, quality=quality_ocr(raw, features, derived, self.fcfg))
        return entry

    # ---- một PDF
    def process_pdf(self, path: Path) -> dict:
        pages = []
        with pymupdf.open(path) as doc:
            page_count = len(doc)
            for i, page in enumerate(doc):
                t0 = time.time()
                entry: dict = {"page": i, "error": None}
                try:
                    f = page_features(page)
                    route, reason = route_of(f, self.min_chars)
                    entry.update(route=route, route_reason=reason, features=f)
                    if route == "text_layer":
                        raw = raw_text_layer(page)
                        derived, dflags = derive_text_layer(raw, f["height"])
                        entry.update(raw=raw, derived=derived, quality=quality_text_layer(raw, f, dflags, reason))
                    else:
                        self._ocr_entry(render_pdf_page(path, i, self.dpi), f, entry)
                except Exception as e:  # noqa: BLE001
                    entry["error"] = f"{type(e).__name__}: {e}"
                entry["seconds"] = round(time.time() - t0, 2)
                pages.append(entry)
        return {"file_kind": "pdf", "page_count": page_count, "pages": pages}

    def process_image(self, path: Path) -> dict:
        t0 = time.time()
        entry: dict = {"page": None, "error": None, "route": "ocr", "route_reason": "file_anh"}
        try:
            img = load_image_file(path)
            f = {"chars": 0, "image_cov": 1.0, "dpi": 0, "landscape": img.width > img.height,
                 "rotation_flag": 0, "height": float(img.height)}
            entry["features"] = f
            self._ocr_entry(img, f, entry)
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"
        entry["seconds"] = round(time.time() - t0, 2)
        return {"file_kind": "image", "page_count": 1, "pages": [entry]}

    # ---- chạy nhiều file
    def is_complete(self, path: Path, sha: str) -> bool:
        out = self.out / f"{path.stem}.json"
        if not out.exists():
            return False
        try:
            d = json.loads(out.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return False
        seal = self.out / f"{path.stem}.json.sha256"
        sealed = seal.exists() and seal.read_text(encoding="utf-8").strip() == sha256_file(out)
        return (d.get("schema") == SCHEMA and d.get("input_sha256") == sha and sealed
                and not any(p.get("error") for p in d["pages"]))

    def run(self, names: list[str] | None = None, limit: int | None = None, force: bool = False,
            shard: tuple[int, int] | None = None) -> None:
        titles = _titles()
        files = sorted(p for p in FILES_DIR.iterdir() if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMG_EXT)
        if shard:  # chia theo vị trí trong danh sách ĐẦY ĐỦ → ổn định giữa các lần chạy lại
            files = [p for i, p in enumerate(files) if i % shard[1] == shard[0]]
        if names:
            files = [p for p in files if any(n in p.name for n in names)]
        todo = []
        for p in files:
            sha = sha256_file(p)
            if force or not self.is_complete(p, sha):
                todo.append((p, sha))
        if limit:
            todo = todo[:limit]
        print(f"Trích xuất: {len(todo)} file cần xử lý ({len(files) - len(todo)} đã xong). Engine nền: {self.base.name}, "
              f"thiết bị: {self.provenance['device']}")
        t_all = time.time()
        for n, (p, sha) in enumerate(todo, 1):
            t0 = time.time()
            doc = self.process_pdf(p) if p.suffix.lower() == ".pdf" else self.process_image(p)
            doc = {"schema": SCHEMA, "file": p.name, "input_sha256": sha, "input_bytes": p.stat().st_size,
                   "source": titles.get(p.name, {}), "pipeline": self.provenance,
                   "processed_at": datetime.now().isoformat(timespec="seconds"), **doc}
            data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            tmp = self.out / f"{p.stem}.json.tmp"
            tmp.write_bytes(data)
            tmp.replace(self.out / f"{p.stem}.json")  # ghi nguyên tử: không để lại file dở dang
            # niêm phong: mã băm của đúng nội dung chương trình vừa ghi; verify sẽ phát hiện mọi chỉnh sửa về sau
            (self.out / f"{p.stem}.json.sha256").write_text(hashlib.sha256(data).hexdigest(), encoding="utf-8")
            ocr = sum(1 for x in doc["pages"] if x.get("route") == "ocr")
            err = sum(1 for x in doc["pages"] if x.get("error"))
            flagged = sum(1 for x in doc["pages"] if x.get("quality", {}).get("flags"))
            print(f"[{n}/{len(todo)}] {p.name[:48]}: {doc['page_count']} trang, OCR {ocr}, cờ {flagged}, lỗi {err}, "
                  f"{time.time() - t0:.0f}s (tổng {(time.time() - t_all) / 60:.1f} phút)", flush=True)


def _titles() -> dict[str, dict]:
    """Metadata nguồn lấy NGUYÊN từ kết quả crawl (không suy diễn)."""
    out: dict[str, dict] = {}
    for p in (RAW_DIR / "pages").glob("*/*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        for f in d.get("files", []):
            lp = f.get("local_path")
            if lp:
                out[Path(lp).name] = {"title": d.get("title", ""), "topic": d.get("topic", ""),
                                      "date": d.get("date"), "page_url": d["url"]}
    return out


# ------------------------------------------------------------------- kiểm chứng
def verify(cfg: dict | None = None, deep: bool = True) -> dict:
    """Kiểm tra: đủ file, khớp mã băm, đủ số trang, không lỗi, và derived/quality == hàm của raw (không bị sửa tay)."""
    cfg = cfg or load_config("ocr")
    out = out_dir(cfg)
    fcfg = cfg["flags"]
    files = sorted(p for p in FILES_DIR.iterdir() if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMG_EXT)
    problems: dict[str, list] = {"thieu_ket_qua": [], "ma_bam_khong_khop": [], "schema_cu": [], "so_trang_lech": [],
                                 "trang_loi": [], "derived_bi_sua": [], "quality_bi_sua": [], "ket_qua_mo_coi": [],
                                 "file_bi_sua_sau_khi_ghi": []}
    stats = {"files": len(files), "pages": 0, "route": Counter(), "flags": Counter(), "empty_text_pages": 0,
             "ocr_seconds": 0.0, "engines": Counter()}
    names = {p.stem for p in files}
    for jp in out.glob("*.json"):
        if jp.stem not in names and not jp.name.startswith("_"):
            problems["ket_qua_mo_coi"].append(jp.name)
    for p in files:
        jp = out / f"{p.stem}.json"
        if not jp.exists():
            problems["thieu_ket_qua"].append(p.name)
            continue
        seal = out / f"{p.stem}.json.sha256"
        if not seal.exists() or seal.read_text(encoding="utf-8").strip() != sha256_file(jp):
            problems["file_bi_sua_sau_khi_ghi"].append(p.name)
        d = json.loads(jp.read_text(encoding="utf-8"))
        if d.get("schema") != SCHEMA:
            problems["schema_cu"].append(p.name)
            continue
        if d["input_sha256"] != sha256_file(p):
            problems["ma_bam_khong_khop"].append(p.name)
        if p.suffix.lower() == ".pdf":
            with pymupdf.open(p) as doc:
                if len(doc) != d["page_count"] or len(d["pages"]) != len(doc):
                    problems["so_trang_lech"].append(p.name)
        for pg in d["pages"]:
            stats["pages"] += 1
            if pg.get("error"):
                problems["trang_loi"].append(f"{p.name} p{pg['page']}: {pg['error']}")
                continue
            stats["route"][pg["route"]] += 1
            stats["ocr_seconds"] += pg.get("seconds", 0) if pg["route"] == "ocr" else 0
            for fl in pg["quality"]["flags"]:
                stats["flags"][fl] += 1
            if not pg["derived"]["text"].strip():
                stats["empty_text_pages"] += 1
            stats["engines"][pg["raw"]["engine"]] += 1
            if not deep:
                continue
            if pg["route"] == "ocr":
                derived = derive_ocr(pg["raw"])
                qual = quality_ocr(pg["raw"], pg["features"], derived, fcfg)
                ok_q = qual["flags"] == pg["quality"]["flags"]
            else:
                derived, dflags = derive_text_layer(pg["raw"], pg["features"]["height"])
                qual = quality_text_layer(pg["raw"], pg["features"], dflags, pg["route_reason"])
                ok_q = qual["flags"] == pg["quality"]["flags"]
            if derived != pg["derived"]:
                problems["derived_bi_sua"].append(f"{p.name} p{pg['page']}")
            if not ok_q:
                problems["quality_bi_sua"].append(f"{p.name} p{pg['page']}")
    ok = not any(problems.values())
    report = {"ok": ok, "checked_at": datetime.now().isoformat(timespec="seconds"),
              "stats": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in stats.items()},
              "problems": problems}
    (out / "_verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report

"""Benchmark OCR: chọn mẫu phủ các trường hợp → chạy nhiều công cụ → báo cáo so sánh.

Các bước (chạy qua scripts/ocr_benchmark.py):
    stats   quét toàn bộ PDF, lưu đặc điểm từng trang (hướng, xoay, DPI, có lớp text...)
    sample  chọn mẫu phủ từng nhóm đặc điểm → data/eval/ocr_sample.json
    run     OCR từng trang mẫu bằng từng công cụ → data/eval/ocr_runs/
    report  tính chỉ số, viết data/eval/ocr_report.md

Đáp án (truth):
    - Trang PDF có lớp text: lấy text gốc làm đáp án TỰ ĐỘNG (dùng để hiệu chuẩn công cụ).
    - Trang scan: không có đáp án tự động. Muốn chấm chính xác, tự gõ lại nội dung vào
      data/eval/ocr_truth/<id>.txt; báo cáo sẽ dùng file này nếu có.
"""
from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pymupdf

from rag.config import EVAL_DIR, RAW_DIR, load_config
from rag.ingestion.ocr_engines import (
    build_engines, detect_rotation, load_image_file, render_pdf_page, words_to_text,
)

STATS_PATH = EVAL_DIR / "ocr_page_stats.json"
SAMPLE_PATH = EVAL_DIR / "ocr_sample.json"
RUNS_DIR = EVAL_DIR / "ocr_runs"
TRUTH_DIR = EVAL_DIR / "ocr_truth"
REPORT_PATH = EVAL_DIR / "ocr_report.md"
FILES_DIR = RAW_DIR / "files"


# ------------------------------------------------------------------ tiện ích
def _norm_vi(text: str) -> str:
    """Hạ chữ thường, bỏ dấu để so từ khóa."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _slug(text: str, limit: int = 90) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:limit]


def item_id(file: str, page: int | None) -> str:
    stem = Path(file).stem
    return _slug(stem if page is None else f"{stem}-p{page}")


# -------------------------------------------------------------- 1. thống kê
def scan_pdf_pages(force: bool = False) -> list[dict]:
    """Đặc điểm từng trang PDF. Kết quả được lưu đệm để không phải quét lại."""
    if STATS_PATH.exists() and not force:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    rows: list[dict] = []
    files = sorted(FILES_DIR.glob("*.pdf"))
    for n, f in enumerate(files, 1):
        try:
            doc = pymupdf.open(f)
        except Exception:  # noqa: BLE001
            continue
        for i, p in enumerate(doc):
            chars = len(p.get_text().strip())
            cov, dpi = 0.0, 0
            for im in p.get_image_info():
                inter = pymupdf.Rect(im["bbox"]) & p.rect
                if not inter.is_empty:
                    c = inter.get_area() / p.rect.get_area()
                    if c > cov:
                        cov = c
                        span_in = (p.rect.width if p.rotation in (0, 180) else p.rect.height) / 72
                        dpi = round(im["width"] / span_in) if span_in else 0
            if chars >= 50 and cov < 0.5:
                kind = "text"
            elif chars < 50 and cov >= 0.5:
                kind = "scan"
            else:
                kind = "other"
            rows.append({"file": f.name, "page": i, "chars": chars, "cov": round(cov, 2), "dpi": dpi,
                         "landscape": p.rect.width > p.rect.height, "rotation": p.rotation, "kind": kind})
        if n % 50 == 0:
            print(f"  quét {n}/{len(files)} file")
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def _titles() -> dict[str, dict]:
    """tên file đính kèm → {title, topic, url} của trang chứa nó."""
    out: dict[str, dict] = {}
    for p in (RAW_DIR / "pages").glob("*/*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        for f in d.get("files", []):
            lp = f.get("local_path")
            if lp:
                out[Path(lp).name] = {"title": d.get("title", ""), "topic": d.get("topic", ""), "url": d["url"]}
    return out


# ------------------------------------------------------------------ 2. mẫu
def _pick(items: list[dict], n: int, rng: random.Random, preferred) -> list[dict]:
    """Chọn n trang, ưu tiên các file khác nhau và file có tiêu đề kiểu bảng."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in items:
        by_file[r["file"]].append(r)
    files = list(by_file)
    rng.shuffle(files)
    files.sort(key=lambda f: not preferred(f))
    picks = [rng.choice(by_file[f]) for f in files[:n]]
    pool = [r for r in items if r not in picks]
    rng.shuffle(pool)
    return picks + pool[: max(0, n - len(picks))]


def _has_table(path: Path, page: int) -> bool:
    try:
        with pymupdf.open(path) as d:
            return len(d[page].find_tables().tables) > 0
    except Exception:  # noqa: BLE001
        return False


def build_sample(cfg: dict | None = None, rescan: bool = False) -> dict:
    cfg = cfg or load_config("ocr")
    sc = cfg["sample"]
    rng = random.Random(sc["seed"])
    rows = scan_pdf_pages(force=rescan)
    titles = _titles()
    kws = [_norm_vi(k) for k in sc.get("table_keywords", [])]

    def preferred(fname: str) -> bool:
        t = _norm_vi(titles.get(fname, {}).get("title", ""))
        return any(k in t for k in kws)

    items: list[dict] = []

    def add(r: dict, stratum: str, truth: str | None = None, **extra) -> None:
        meta = titles.get(r["file"], {})
        items.append({
            "id": item_id(r["file"], r["page"]), "file": r["file"], "page": r["page"], "kind": r["kind"],
            "stratum": stratum, "landscape": r["landscape"], "rotation_flag": r["rotation"], "dpi": r["dpi"],
            "title": meta.get("title", ""), "topic": meta.get("topic", ""), "truth": truth, **extra,
        })

    # (a) trang scan: mỗi nhóm (hướng × cờ xoay × DPI) lấy vài trang
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] == "scan":
            strata[("ngang" if r["landscape"] else "dọc", r["rotation"], "dpi<200" if r["dpi"] < 200 else "dpi>=200")].append(r)
    for key, rs in sorted(strata.items(), key=lambda x: -len(x[1])):
        n = sc["per_big_stratum"] if len(rs) >= sc["big_stratum_pages"] else sc["per_small_stratum"]
        for r in _pick(rs, n, rng, preferred):
            add(r, f"scan|{key[0]}|xoay{key[1]}|{key[2]}")

    # (b) trang có lớp text: đáp án tự động để hiệu chuẩn công cụ
    texts = [r for r in rows if r["kind"] == "text"]
    land = [r for r in texts if r["landscape"]]
    rng.shuffle(land)
    with_table = [r for r in land[:40] if _has_table(FILES_DIR / r["file"], r["page"])]
    land_pick = (with_table + [r for r in land if r not in with_table])[: sc["text_landscape"]]
    for r in land_pick:
        add(r, "text|ngang" + ("|có bảng" if r in with_table else ""), truth="pdf_text")
    port = [r for r in texts if not r["landscape"]]
    for r in _pick(port, sc["text_portrait"], rng, preferred):
        add(r, "text|dọc", truth="pdf_text")

    # (c) file ảnh
    imgs = sorted(p for p in FILES_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    for p in imgs[: sc["max_images"]]:
        meta = titles.get(p.name, {})
        items.append({"id": item_id(p.name, None), "file": p.name, "page": None, "kind": "image",
                      "stratum": "ảnh", "landscape": None, "rotation_flag": 0, "dpi": 0,
                      "title": meta.get("title", ""), "topic": meta.get("topic", ""), "truth": None})

    # (d) trang chọn tay
    for spec in sc.get("manual_pages", []):
        fname, _, pg = spec.partition("#")
        match = [r for r in rows if r["file"] == fname and r["page"] == int(pg or 0)]
        if match:
            add(match[0], "thủ công")

    seen, uniq = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            uniq.append(it)
    out = {"created": datetime.now().isoformat(timespec="seconds"), "seed": sc["seed"], "items": uniq}
    SAMPLE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ------------------------------------------------------------------ 3. chạy
def _load_item_image(it: dict, dpi: int):
    path = FILES_DIR / it["file"]
    return load_image_file(path) if it["kind"] == "image" else render_pdf_page(path, it["page"], dpi)


def _safe(name: str) -> str:
    return name.replace(":", "_")


def run_benchmark(cfg: dict | None = None, engine_specs: list[str] | None = None,
                  force: bool = False, limit: int | None = None) -> dict:
    cfg = cfg or load_config("ocr")
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["items"]
    if limit:
        sample = sample[:limit]
    engines, bad = build_engines(engine_specs or cfg["engines"], cfg)
    for name, why in bad.items():
        print(f"  ! bỏ qua {name}: {why}")
    if not engines:
        raise SystemExit("Không có công cụ OCR nào dùng được.")

    ocfg = cfg.get("orientation", {})
    orienter = None
    if ocfg.get("enabled", True):
        orienter = engines.get(ocfg.get("engine")) or next(iter(engines.values()))

    results_path = RUNS_DIR / "results.json"
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "images").mkdir(exist_ok=True)
    (RUNS_DIR / "truth").mkdir(exist_ok=True)
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}

    for n, it in enumerate(sample, 1):
        res = results.setdefault(it["id"], {"engines": {}})
        todo = [e for e in engines if force or e not in res["engines"]
                or not (RUNS_DIR / _safe(e) / f"{it['id']}.txt").exists()]
        if not todo and "rotation" in res:
            continue
        print(f"[{n}/{len(sample)}] {it['id']}  ({it['stratum']})")
        try:
            img = _load_item_image(it, cfg.get("render_dpi", 200))
        except Exception as e:  # noqa: BLE001
            res["error"] = f"{type(e).__name__}: {e}"
            print(f"   ! không dựng được ảnh: {e}")
            continue
        if "rotation" not in res or force:
            res["rotation"] = detect_rotation(img, orienter, ocfg.get("max_side", 1400)) if orienter else 0
        if res["rotation"]:
            img = img.rotate(res["rotation"], expand=True)
        img.save(RUNS_DIR / "images" / f"{it['id']}.jpg", quality=80)
        if it.get("truth") == "pdf_text":
            with pymupdf.open(FILES_DIR / it["file"]) as d:
                (RUNS_DIR / "truth" / f"{it['id']}.txt").write_text(d[it["page"]].get_text(), encoding="utf-8")

        for name in todo:
            t0 = time.time()
            try:
                words = engines[name].run(img)
                text = words_to_text(words)
                confs = [w.conf for w in words if w.conf is not None]
                stats = {"seconds": round(time.time() - t0, 2), "chars": len(text), "words": len(words),
                         "mean_conf": round(sum(confs) / len(confs), 3) if confs else None}
            except Exception as e:  # noqa: BLE001
                text, stats = "", {"seconds": round(time.time() - t0, 2), "error": f"{type(e).__name__}: {e}"}
            d = RUNS_DIR / _safe(name)
            d.mkdir(exist_ok=True)
            (d / f"{it['id']}.txt").write_text(text, encoding="utf-8")
            res["engines"][name] = stats
            print(f"   {name}: {stats.get('seconds')}s, {stats.get('chars', 0)} ký tự, xoay {res['rotation']}°")
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    results["_unavailable"] = bad
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


# ---------------------------------------------------------------- 4. báo cáo
def _squash(text: str, strip_marks: bool = False) -> str:
    s = unicodedata.normalize("NFC", text).replace(" | ", " ")
    if strip_marks:
        s = _norm_vi(s)
    return re.sub(r"\s+", "", s).lower()


def _lev(a: str, b: str) -> int:
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(a, b)
    except ImportError:  # chậm hơn và chỉ xấp xỉ
        from difflib import SequenceMatcher
        return round((1 - SequenceMatcher(None, a[:4000], b[:4000], autojunk=False).ratio()) * max(len(a), len(b), 1))


def cer(ref: str, hyp: str, strip_marks: bool = False) -> float:
    r, h = _squash(ref, strip_marks), _squash(hyp, strip_marks)
    return _lev(r, h) / max(1, len(r))


NUM_RE = re.compile(r"\d+(?:[.,/:\-]\d+)*")


def number_f1(ref: str, hyp: str) -> float:
    a, b = Counter(NUM_RE.findall(ref)), Counter(NUM_RE.findall(hyp))
    if not a and not b:
        return 1.0
    tp = sum((a & b).values())
    if not tp:
        return 0.0
    p, r = tp / sum(b.values()), tp / sum(a.values())
    return 2 * p * r / (p + r)


WORD_RE = re.compile(r"\w+", re.UNICODE)


def word_f1(ref: str, hyp: str, strip_marks: bool = False) -> float:
    """F1 theo từ, KHÔNG phụ thuộc thứ tự đọc (CER bị đội lên khi thứ tự đọc khác đáp án)."""
    def toks(s: str) -> Counter:
        s = unicodedata.normalize("NFC", s).lower()
        return Counter(WORD_RE.findall(_norm_vi(s) if strip_marks else s))
    a, b = toks(ref), toks(hyp)
    tp = sum((a & b).values())
    if not tp:
        return 0.0
    p, r = tp / sum(b.values()), tp / sum(a.values())
    return 2 * p * r / (p + r)


def _truth_for(it: dict) -> tuple[str | None, str | None]:
    manual = TRUTH_DIR / f"{it['id']}.txt"
    if manual.exists():
        return manual.read_text(encoding="utf-8"), "thủ công"
    auto = RUNS_DIR / "truth" / f"{it['id']}.txt"
    if it.get("truth") == "pdf_text" and auto.exists():
        return auto.read_text(encoding="utf-8"), "text PDF"
    return None, None


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _fmt(x: float | None, pct: bool = False, nd: int = 1) -> str:
    if x is None:
        return "–"
    return f"{x * 100:.{nd}f}%" if pct else f"{x:.{nd}f}"


def make_report() -> str:
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["items"]
    results = json.loads((RUNS_DIR / "results.json").read_text(encoding="utf-8"))
    unavailable = results.get("_unavailable", {})
    engines = sorted({e for it in sample for e in results.get(it["id"], {}).get("engines", {})})

    text_of: dict[tuple[str, str], str] = {}
    for it in sample:
        for e in engines:
            p = RUNS_DIR / _safe(e) / f"{it['id']}.txt"
            if p.exists():
                text_of[(it["id"], e)] = p.read_text(encoding="utf-8")

    # chỉ số theo từng (mẫu, công cụ)
    rows = []
    for it in sample:
        truth, tsrc = _truth_for(it)
        res = results.get(it["id"], {})
        for e in engines:
            hyp = text_of.get((it["id"], e))
            if hyp is None:
                continue
            st = res.get("engines", {}).get(e, {})
            row = {"id": it["id"], "stratum": it["stratum"], "engine": e, "sec": st.get("seconds"),
                   "conf": st.get("mean_conf"), "chars": len(hyp), "truth_src": tsrc, "error": st.get("error")}
            if truth:
                row["cer"] = cer(truth, hyp)
                row["cer_nomark"] = cer(truth, hyp, strip_marks=True)
                row["num_f1"] = number_f1(truth, hyp)
                row["word_f1"] = word_f1(truth, hyp)
                row["word_f1_nomark"] = word_f1(truth, hyp, strip_marks=True)
            others = [text_of[(it["id"], o)] for o in engines if o != e and (it["id"], o) in text_of]
            row["agree"] = _mean([1 - min(1.0, cer(o, hyp)) for o in others if o.strip()]) if others else None
            rows.append(row)

    out = ["# Báo cáo benchmark OCR", "",
           f"_Tạo lúc {datetime.now():%Y-%m-%d %H:%M} · {len(sample)} mẫu · công cụ: {', '.join(engines) or 'không có'}_", ""]
    if unavailable:
        out += ["**Công cụ không dùng được:**"] + [f"- `{k}`: {v}" for k, v in unavailable.items()] + [""]

    out += ["## 1. Tổng hợp theo công cụ", "",
            "- **CER** = tỷ lệ ký tự sai so với đáp án (thấp hơn là tốt). **CER không dấu** bỏ qua lỗi dấu tiếng Việt, "
            "nên hiệu giữa hai cột cho biết công cụ sai chủ yếu ở dấu hay ở chữ cái.",
            "- **F1 từ** đo đúng/sai theo từ, không phụ thuộc thứ tự đọc nên công bằng hơn CER khi bố cục khác nhau; "
            "**F1 từ không dấu** bỏ qua dấu — khoảng cách giữa hai cột là mức lỗi do dấu tiếng Việt.",
            "- **F1 số** đo độ chính xác các chuỗi số (ngày, tiền, mã) — quan trọng với học phí, lịch thi.",
            "- Đáp án ở đây là **text gốc của PDF** (trang có lớp text). Đây là mức hiệu chuẩn; chất lượng trên trang scan "
            "thật có thể thấp hơn.", "",
            "| Công cụ | F1 từ | F1 từ không dấu | CER | F1 số | Giây/trang | Tin cậy TB | Lỗi |", "|---|---|---|---|---|---|---|---|"]
    for e in engines:
        rs = [r for r in rows if r["engine"] == e]
        tr = [r for r in rs if "cer" in r and r["truth_src"] == "text PDF"]
        out.append(f"| `{e}` | {_fmt(_mean([r['word_f1'] for r in tr]), True)} | {_fmt(_mean([r['word_f1_nomark'] for r in tr]), True)} "
                   f"| {_fmt(_mean([r['cer'] for r in tr]), True)} "
                   f"| {_fmt(_mean([r['num_f1'] for r in tr]), True)} | {_fmt(_mean([r['sec'] for r in rs]))} "
                   f"| {_fmt(_mean([r['conf'] for r in rs]), True)} | {sum(1 for r in rs if r['error'])} |")

    manual = [r for r in rows if r.get("truth_src") == "thủ công"]
    if manual:
        out += ["", "### Trang scan có đáp án gõ tay", "", "| Công cụ | F1 từ | CER | CER không dấu | F1 số | Số trang |", "|---|---|---|---|---|---|"]
        for e in engines:
            tr = [r for r in manual if r["engine"] == e]
            if tr:
                out.append(f"| `{e}` | {_fmt(_mean([r['word_f1'] for r in tr]), True)} "
                           f"| {_fmt(_mean([r['cer'] for r in tr]), True)} | {_fmt(_mean([r['cer_nomark'] for r in tr]), True)} "
                           f"| {_fmt(_mean([r['num_f1'] for r in tr]), True)} | {len(tr)} |")

    out += ["", "## 2. Theo nhóm trang (độ đồng thuận giữa các công cụ)", "",
            "Với trang scan chưa có đáp án, **đồng thuận** = mức giống nhau trung bình với các công cụ còn lại. "
            "Đồng thuận cao chưa chắc đúng, nhưng đồng thuận thấp là dấu hiệu trang khó.", "",
            "| Nhóm | Công cụ | Số trang | Đồng thuận | Tin cậy TB | Giây/trang |", "|---|---|---|---|---|---|"]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["stratum"], r["engine"])].append(r)
    for (s, e), rs in sorted(groups.items()):
        out.append(f"| {s} | `{e}` | {len(rs)} | {_fmt(_mean([r['agree'] for r in rs]), True)} "
                   f"| {_fmt(_mean([r['conf'] for r in rs]), True)} | {_fmt(_mean([r['sec'] for r in rs]))} |")

    # trang nên gõ đáp án: scan, đồng thuận thấp nhất
    scan_rows: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["truth_src"] is None and r["agree"] is not None:
            scan_rows[r["id"]].append(r["agree"])
    hard = sorted(((sum(v) / len(v), k) for k, v in scan_rows.items()))[:8]
    if hard:
        out += ["", "## 3. Trang nên gõ đáp án tay (khó nhất)", "",
                f"Ảnh trang (đã xoay đúng hướng) nằm ở `data/eval/ocr_runs/images/`. Gõ nội dung vào "
                f"`data/eval/ocr_truth/<id>.txt` rồi chạy lại `report` để có CER thật.", "",
                "| id | Đồng thuận | Nhóm |", "|---|---|---|"]
        by_id = {it["id"]: it for it in sample}
        for score, k in hard:
            out.append(f"| `{k}` | {_fmt(score, True)} | {by_id[k]['stratum']} |")

    out += ["", "## 4. Chi tiết từng mẫu", "",
            "| id | Nhóm | Xoay | Công cụ | CER | F1 số | Đồng thuận | Giây |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| `{r['id'][:60]}` | {r['stratum']} | {results[r['id']].get('rotation', 0)}° | `{r['engine']}` "
                   f"| {_fmt(r.get('cer'), True)} | {_fmt(r.get('num_f1'), True)} | {_fmt(r['agree'], True)} | {_fmt(r['sec'])} |")

    out += ["", "## 5. Đối chiếu bằng mắt", "",
            "Với mỗi mẫu, so sánh ảnh `ocr_runs/images/<id>.jpg` với `ocr_runs/<công cụ>/<id>.txt`. "
            "Chú ý bảng (cột có bị dính không), dấu tiếng Việt, và các con số."]
    REPORT_PATH.write_text("\n".join(out), encoding="utf-8")
    return "\n".join(out)

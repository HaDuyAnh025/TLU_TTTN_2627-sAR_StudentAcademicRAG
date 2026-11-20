"""LLM rà soát OCR → người xác nhận TỪNG CHỖ nghi ngờ (ảnh cắt đúng vùng + hai cách đọc), không đọc cả trang.

Các bước (scripts/ingest.py):
  --stage llm-review          LLM so ảnh trang với văn bản OCR, liệt kê chỗ khác nhau  → data/eval/llm_review/<id>.json
  --stage review-items        dựng trang web kiểm tra từng chỗ + một ít trang "LLM bảo sạch" để kiểm tra bỏ sót → data/eval/review_items/
  --stage review-items-score  đọc CSV bạn đã điền → data/eval/review_items_score.md + lớp sửa lỗi tách riêng

Nguyên tắc (giữ nguyên quy ước dự án):
  - KHÔNG sửa gì trong data/interim/extract. LLM chỉ ĐỀ XUẤT; kết quả nằm riêng ở data/eval.
  - LLM bị yêu cầu chỉ trích nguyên văn hai bên (OCR và ảnh), không viết lại cả trang, không đoán chỗ không nhìn thấy.
  - Chỗ nào chỉ được đưa vào lớp sửa lỗi (data/eval/review_items/confirmed_corrections.jsonl) khi NGƯỜI xác nhận "LLM đúng"
    hoặc tự điền văn bản đúng. Lớp này tách riêng, có nguồn gốc; ai dùng lớp này là quyết định ở bước sau.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from rag.config import EVAL_DIR, load_config
from rag.evaluation.extract_eval import TRIGGER, load_docs
from rag.evaluation.review_pack import PACK, wilson
from rag.ingestion.ocr_engines import load_image_file, render_pdf_page
from rag.ingestion.vlm_ocr import model_ready
from rag.ingestion.loader import FILES_DIR

LLM_DIR = EVAL_DIR / "llm_review"
ITEMS_DIR = EVAL_DIR / "review_items"
SCORE_MD = EVAL_DIR / "review_items_score.md"

PROMPT = """Bạn là người rà soát kết quả OCR của một trang tài liệu hành chính đại học (tiếng Việt).
Bạn được cho: (1) ẢNH của trang, (2) VĂN BẢN OCR của trang (bên dưới).
Nhiệm vụ: chỉ liệt kê những chỗ văn bản OCR KHÁC với những gì nhìn thấy trên ảnh: sai chữ hoặc dấu tiếng Việt, sai chữ số, dòng thiếu hoặc thừa, bảng sai cột.
Quy tắc bắt buộc:
- KHÔNG viết lại cả trang, KHÔNG sửa những chỗ đã đúng, KHÔNG đoán chỗ bạn không nhìn thấy rõ trên ảnh.
- Mỗi chỗ lỗi: "ocr" = đoạn NGẮN (3 đến 12 từ) trích NGUYÊN VĂN từ văn bản OCR đúng như nó xuất hiện (để chương trình tìm lại được); "anh" = đoạn tương ứng bạn đọc được trên ảnh, nguyên văn.
- "loai": so_lieu (tiền, ngày, giờ, mã, số điện thoại), chu_dau (sai chữ/dấu), thieu_dong, thua_dong, bang, khac.
- "quan_trong": true nếu là số liệu, tên riêng, hoặc làm đổi nghĩa; ngược lại false.
- "do_chac": cao, trung_binh hoặc thap (mức chắc chắn của bạn về chỗ khác này).
- Nếu không thấy chỗ nào khác, trả "co_loi": false và "loi": [].
Chỉ trả về MỘT đối tượng JSON, không thêm chữ nào khác:
{"co_loi": true, "loi": [{"ocr": "...", "anh": "...", "loai": "so_lieu", "quan_trong": true, "do_chac": "cao"}]}

VĂN BẢN OCR CỦA TRANG:
"""


# ------------------------------------------------------------------ tiện ích
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFC", t or "").lower().replace("|", " ")
    return re.sub(r"\s+", " ", t).strip()


def page_key(doc: dict, pg: dict) -> str:
    stem = Path(doc["file"]).stem
    raw = stem if pg["page"] is None else f"{stem}-p{pg['page']}"
    return "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in raw)[:90]


def render_page(doc: dict, pg: dict, dpi: int):
    path = FILES_DIR / doc["file"]
    img = load_image_file(path) if doc["file_kind"] == "image" else render_pdf_page(path, pg["page"], dpi)
    if pg["route"] == "ocr" and pg["raw"]["orientation"]["angle_ccw"]:
        img = img.rotate(pg["raw"]["orientation"]["angle_ccw"], expand=True)
    return img


def parse_json(text: str) -> dict | None:
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(text[i:j + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("loi", []), list):
        return None
    return d


def ocr_lines(words: list[dict]) -> list[list[dict]]:
    """Gom các khối chữ OCR thành dòng ĐÚNG như words_to_text (để vị trí khớp chính xác với văn bản OCR đã lưu)."""
    if not words:
        return []
    heights = sorted(max(1.0, w["box"][3] - w["box"][1]) for w in words)
    med = heights[len(heights) // 2]
    ordered = sorted(words, key=lambda w: (w["box"][1] + w["box"][3]) / 2)
    lines: list[dict] = []
    for w in ordered:
        cy = (w["box"][1] + w["box"][3]) / 2
        if lines and abs(cy - lines[-1]["cy"]) <= med * 0.6:
            lines[-1]["w"].append(w)
            lines[-1]["cy"] = sum((x["box"][1] + x["box"][3]) / 2 for x in lines[-1]["w"]) / len(lines[-1]["w"])
        else:
            lines.append({"cy": cy, "w": [w]})
    return [sorted(ln["w"], key=lambda w: w["box"][0]) for ln in lines]


def _text_with_spans(words: list[dict]) -> tuple[str, list[tuple[int, int, list]]]:
    """Văn bản OCR (giống derived.text) kèm khoảng ký tự của từng khối chữ → [(bắt_đầu, kết_thúc, khung)]."""
    lines = ocr_lines(words)
    heights = sorted(max(1.0, w["box"][3] - w["box"][1]) for w in words)
    med = heights[len(heights) // 2]
    out, spans, pos = [], [], 0
    for ln in lines:
        s = ""
        for i, w in enumerate(ln):
            if i:
                sep = " | " if w["box"][0] - ln[i - 1]["box"][2] > med * 2.5 else " "
                s += sep
            start = pos + len(s)
            s += w["text"]
            spans.append((start, pos + len(s), w["box"]))
        out.append(s)
        pos += len(s) + 1  # +1 cho ký tự xuống dòng
    return chr(10).join(out), spans


def _squash_map(text: str) -> tuple[str, list[int]]:
    """Bỏ '|', gộp khoảng trắng, hạ chữ thường; trả kèm vị trí gốc của từng ký tự để quy ngược."""
    chars, idx, prev_space = [], [], True
    for i, c in enumerate(unicodedata.normalize("NFC", text)):
        if c == "|":
            continue
        if c.isspace():
            if prev_space:
                continue
            chars.append(" ")
            idx.append(i)
            prev_space = True
        else:
            chars.append(c.lower())
            idx.append(i)
            prev_space = False
    return "".join(chars), idx


def _union(boxes: list) -> list:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def locate(pg: dict, snippet: str, dpi: int) -> dict | None:
    """Tìm CHÍNH XÁC vị trí đoạn 'ocr' LLM trích: tìm nguyên văn trong văn bản OCR rồi lấy khung của đúng các từ tạo nên
    đoạn đó. Không tìm thấy chắc chắn thì trả None (giao diện sẽ hiện cả trang) thay vì khoanh nhầm chỗ."""
    sn = _norm(snippet)
    if len(sn) < 3:
        return None
    if pg["route"] == "ocr":
        words = pg["raw"]["words"]
        if not words:
            return None
        text, spans = _text_with_spans(words)
        norm_text, idx = _squash_map(text)
        sq, _ = _squash_map(snippet)
        sq = sq.strip()
        pos = norm_text.find(sq) if sq else -1
        if pos < 0:
            return None
        a, b = idx[pos], idx[pos + len(sq) - 1] + 1  # khoảng ký tự trong văn bản gốc
        hit = [s[2] for s in spans if s[0] < b and s[1] > a]
        if not hit:
            return None
        return {"box": [round(v, 1) for v in _union(hit)], "score": 100.0, "cach": "khop_nguyen_van"}
    k = dpi / 72  # trang có lớp text: khung của khối (đoạn văn) chứa đoạn trích
    best = None
    for b in pg["raw"]["blocks"]:
        if b[6] != 0:
            continue
        bs, _ = _squash_map(b[4])
        sq, _ = _squash_map(snippet)
        if sq.strip() and sq.strip() in bs:
            best = [b[0] * k, b[1] * k, b[2] * k, b[3] * k]
            break
    return {"box": [round(v, 1) for v in best], "score": 100.0, "cach": "khop_nguyen_van"} if best else None


# ------------------------------------------------------------------ 1. LLM rà soát
def select_pages(cfg: dict, scope: str) -> list[tuple[dict, dict]]:
    docs = load_docs(cfg)
    index = {(d["file"], p["page"]): (d, p) for d in docs for p in d["pages"] if not p.get("error")}
    if scope == "pack":
        f = PACK / "review_sheet.csv"
        if not f.exists():
            raise SystemExit("Chưa có gói mẫu: chạy --stage review-pack trước (hoặc dùng --scope flagged).")
        out = []
        for r in csv.DictReader(f.open(encoding="utf-8-sig")):
            k = (r["file"], int(r["trang"]) if r["trang"] != "" else None)
            if k in index:
                out.append(index[k])
        return out
    pages = [v for v in index.values() if v[1]["route"] == "ocr"]
    if scope == "flagged":
        pages = [v for v in pages if TRIGGER & set(v[1]["quality"]["flags"])]
    return pages


def page_context(pg: dict) -> str:
    """Thông tin cờ của trang, giúp LLM tập trung kiểm tra đúng chỗ nghi ngờ (không chứa nội dung suy diễn)."""
    q = pg["quality"]
    out = []
    if q["flags"]:
        out.append("Chương trình đã gắn cờ nghi ngờ cho trang này: " + ", ".join(q["flags"]) + ".")
    nm = (q.get("detail") or {}).get("number_mismatch")
    if nm and nm.get("examples"):
        out.append("Hai công cụ OCR đọc KHÁC NHAU các chuỗi số sau, hãy kiểm tra kỹ trên ảnh: " + ", ".join(nm["examples"]) + ".")
    if "table_suspected" in q["flags"]:
        out.append("Trang có bảng: kiểm tra từng ô số liệu và tiêu đề cột.")
    return chr(10).join(out) + chr(10) * 2 if out else ""


def run_review(cfg: dict | None = None, scope: str = "pack", limit: int | None = None, dry_run: bool = False,
               out_dir: Path | None = None, caller=None, model_override: str | None = None, workers: int = 1) -> dict:
    cfg = cfg or load_config("ocr")
    vcfg = dict(cfg["vlm"])
    if model_override:  # đổi mô hình bằng dòng lệnh, không phải sửa file cấu hình
        if vcfg["provider"] == "openai":
            vcfg["openai"] = {**(vcfg.get("openai") or {}), "model": model_override}
        else:
            vcfg["model"] = model_override
    out_dir = out_dir or LLM_DIR
    prov, model, has_key, env_name, fn = model_ready(vcfg)
    todo = [(d, p) for d, p in select_pages(cfg, scope) if not (out_dir / f"{page_key(d, p)}.json").exists()]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} trang cần LLM rà soát (phạm vi: {scope}). Nhà cung cấp: {prov} · mô hình: {model or '(CHƯA ĐIỀN)'} · "
          f"khóa {env_name}: {'có' if has_key else 'chưa có'}")
    print(f"Ước tính thô ~{len(todo) * 2450:,} token vào (ảnh ~1.750 + văn bản OCR ~700) và ~{len(todo) * 200:,} token ra; "
          "chưa nhân giá → chạy thử --limit 10 để đo.")
    if caller is None and (dry_run or not has_key or not model):
        print("Chỉ liệt kê, không gọi." if dry_run else
              ("Chưa điền vlm.<nhà cung cấp>.model trong configs/ocr.yaml." if not model else f"Chưa có {env_name}."))
        return {"pages": len(todo), "called": 0}
    out_dir.mkdir(parents=True, exist_ok=True)
    caller = caller or fn
    prompt_sha = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
    dpi = cfg.get("render_dpi", 200)
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    head, _tail = PROMPT.rsplit("VĂN BẢN OCR CỦA TRANG:", 1)

    def work(d: dict, p: dict) -> tuple[str, int, bool]:
        key = page_key(d, p)
        ocr_text = p["derived"]["text"][:12000]
        full_prompt = head + page_context(p) + "VĂN BẢN OCR CỦA TRANG:" + chr(10) + ocr_text
        img = render_page(d, p, dpi)
        last: Exception | None = None
        for attempt in range(3):  # thử lại khi lỗi mạng hoặc giới hạn tốc độ tạm thời
            try:
                resp, usage = caller(img, vcfg, full_prompt)
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (attempt + 1) ** 2)
        else:
            raise last  # type: ignore[misc]
        parsed = parse_json(resp)
        items = []
        for it in (parsed or {}).get("loi", []):
            if isinstance(it, dict) and it.get("ocr") and it.get("anh") is not None:
                items.append({**it, "vi_tri": locate(p, str(it["ocr"]), dpi)})
        rec = {"id": key, "file": d["file"], "page": p["page"], "route": p["route"], "provider": prov, "model": model,
               "prompt_sha256": prompt_sha, "generated_at": datetime.now().isoformat(timespec="seconds"), "usage": usage,
               "parse_ok": parsed is not None, "co_loi": bool((parsed or {}).get("co_loi")), "loi": items,
               "raw_response": resp,
               "note": "Đề xuất của mô hình, KHÔNG phải kết quả gốc; không ghi đè data/interim/extract."}
        (out_dir / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return key, len(items), parsed is not None

    called = errors = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(work, d, p): page_key(d, p) for d, p in todo}
        for n, f in enumerate(as_completed(futs), 1):
            key = futs[f]
            try:
                key, n_items, ok = f.result()
                called += 1
                el = time.time() - t0
                eta = el / n * (len(todo) - n)
                print(f"  [{n}/{len(todo)}] {key}: {n_items} chỗ nghi ngờ" + ("" if ok else " (KHÔNG đọc được JSON)")
                      + f" · còn khoảng {eta / 60:.0f} phút", flush=True)
            except Exception as e:  # noqa: BLE001
                errors += 1
                print(f"  ! {key}: {type(e).__name__}: {e}", flush=True)
    print(f"Xong: gọi {called}, lỗi {errors}." + (" Chạy lại cùng lệnh để thử lại các trang lỗi." if errors else ""))
    return {"pages": len(todo), "called": called, "errors": errors}


def summarize_dirs(dirs: list[Path]) -> str:
    """So sánh nhanh nhiều thư mục kết quả LLM (mỗi mô hình một thư mục): đọc được JSON, số chỗ nghi ngờ, token, mức trùng nhau."""
    data: dict[str, dict] = {}
    for d in dirs:
        recs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(d).glob("*.json"))}
        data[Path(d).name] = recs
    common = set.intersection(*[set(r) for r in data.values()]) if data else set()
    o = [f"So sánh trên {len(common)} trang chung của {len(data)} thư mục kết quả.", "",
         "| Thư mục | Mô hình | Trang | JSON đọc được | Tổng chỗ nghi ngờ | Chỗ tìm thấy được vị trí | Token vào TB | Token ra TB |",
         "|---|---|---|---|---|---|---|---|"]
    for name, recs in data.items():
        rs = [recs[k] for k in sorted(common)] if common else list(recs.values())
        n = len(rs) or 1
        items = [it for r in rs for it in r.get("loi", [])]
        u_in = [r["usage"]["input_tokens"] for r in rs if r.get("usage", {}).get("input_tokens")]
        u_out = [r["usage"]["output_tokens"] for r in rs if r.get("usage", {}).get("output_tokens")]
        model = next(iter(recs.values()), {}).get("model", "?")
        o.append(f"| `{name}` | `{model}` | {len(rs)} | {sum(1 for r in rs if r.get('parse_ok'))}/{len(rs)} | {len(items)} | "
                 f"{sum(1 for it in items if it.get('vi_tri'))}/{len(items)} | {sum(u_in) // max(len(u_in), 1)} | {sum(u_out) // max(len(u_out), 1)} |")
    names = list(data)
    if len(names) >= 2 and common:
        o += ["", "**Mức trùng nhau về chỗ nghi ngờ** (cùng đoạn OCR bị nêu; chỉ báo thô, không phải độ chính xác):", ""]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                inter = uni = 0
                for k in common:
                    a = {_norm(it.get("ocr", "")) for it in data[names[i]][k].get("loi", [])}
                    b = {_norm(it.get("ocr", "")) for it in data[names[j]][k].get("loi", [])}
                    inter += len(a & b)
                    uni += len(a | b)
                o.append(f"- `{names[i]}` và `{names[j]}`: {inter}/{uni} đoạn trùng ({inter * 100 / uni:.0f}%)" if uni else
                         f"- `{names[i]}` và `{names[j]}`: không có chỗ nghi ngờ nào")
    return chr(10).join(o)


# ------------------------------------------------------------------ 2. trang web kiểm tra từng chỗ
def build_items(cfg: dict | None = None, audit_n: int = 15, seed: int = 42, llm_dir: Path | None = None,
                items_dir: Path | None = None, only_items: set | None = None, auto_items: set | None = None) -> dict:
    """only_items: nếu có, chỉ đưa các chỗ này vào danh sách "cần người xác nhận"; auto_items: các chỗ LLM đã tự sửa,
    đưa vào để người kiểm tra mẫu (kind="auto")."""
    cfg = cfg or load_config("ocr")
    llm_dir = llm_dir or LLM_DIR
    items_dir = items_dir or ITEMS_DIR
    dpi = cfg.get("render_dpi", 200)
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(llm_dir.glob("*.json"))]
    if not recs:
        raise SystemExit(f"Chưa có kết quả LLM trong {llm_dir}: chạy --stage llm-review trước.")
    docs = load_docs(cfg)
    index = {(d["file"], p["page"]): (d, p) for d in docs for p in d["pages"] if not p.get("error")}
    (items_dir / "images").mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    rng = random.Random(seed)
    for rec in recs:
        got = index.get((rec["file"], rec["page"]))
        if not got or not rec.get("parse_ok"):
            continue
        d, p = got
        for k, it in enumerate(rec["loi"]):
            iid = f"{rec['id']}#{k}"
            kind_row = "item"
            if only_items is not None:
                if iid in only_items:
                    kind_row = "item"
                elif auto_items and iid in auto_items:
                    kind_row = "auto"
                else:
                    continue
            img = render_page(d, p, dpi)
            vt = it.get("vi_tri")
            if vt:
                x0, y0, x1, y1 = vt["box"]
                m = 30
                crop = img.crop((max(0, int(x0) - m), max(0, int(y0) - m), min(img.width, int(x1) + m), min(img.height, int(y1) + m)))
                if crop.width < 260:
                    pass
                kind = "vung"
            else:
                crop = img.copy()
                crop.thumbnail((900, 1200))
                kind = "ca_trang"
            safe = iid.replace("#", "_k")
            crop.save(items_dir / "images" / f"{safe}.jpg", quality=85)
            full = f"images/{rec['id']}_full.jpg"
            if not (items_dir / full).exists():
                big = img.copy()
                big.thumbnail((1400, 1900))
                big.save(items_dir / full, quality=80)
            rows.append({"kind": kind_row, "item_id": iid, "trang_id": rec["id"], "file": rec["file"],
                         "trang": "" if rec["page"] is None else rec["page"], "loai": it.get("loai", ""),
                         "quan_trong": "1" if it.get("quan_trong") else "0", "do_chac": it.get("do_chac", ""),
                         "ocr": str(it.get("ocr", "")), "llm_doc": str(it.get("anh", "")), "anh": f"images/{safe}.jpg",
                         "anh_ca_trang": full, "hien_thi": kind})
    clean = [r for r in recs if r.get("parse_ok") and not r["loi"]]
    if only_items is not None:
        audit_n = 0
    rng.shuffle(clean)
    for rec in clean[:audit_n]:
        got = index.get((rec["file"], rec["page"]))
        if not got:
            continue
        d, p = got
        full = f"images/{rec['id']}_full.jpg"
        big = render_page(d, p, dpi)
        big.thumbnail((1400, 1900))
        big.save(items_dir / full, quality=80)
        rows.append({"kind": "audit", "item_id": f"{rec['id']}#audit", "trang_id": rec["id"], "file": rec["file"],
                     "trang": "" if rec["page"] is None else rec["page"], "loai": "", "quan_trong": "", "do_chac": "",
                     "ocr": p["derived"]["text"], "llm_doc": "", "anh": full, "anh_ca_trang": full, "hien_thi": "ca_trang"})
    cols = ["kind", "item_id", "trang_id", "file", "trang", "loai", "quan_trong", "do_chac", "ocr", "llm_doc", "anh",
            "anh_ca_trang", "hien_thi"]
    fill = ["nhan", "sua_thanh", "co_loi_trang", "ghi_chu"]
    with (items_dir / "review_items.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols + fill)
        w.writeheader()
        for r in rows:
            w.writerow({**r, **{c: "" for c in fill}})
    (items_dir / "index.html").write_text(
        HTML.replace("__DATA__", json.dumps(rows, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__COLS__", json.dumps(cols + fill)), encoding="utf-8")
    n_items = sum(1 for r in rows if r["kind"] == "item")
    n_auto = sum(1 for r in rows if r["kind"] == "auto")
    meta = {"pages_reviewed": len(recs), "pages_with_items": len(recs) - len(clean), "items": n_items,
            "auto_audit_items": n_auto, "audit_pages": len(rows) - n_items - n_auto, "clean_pages_total": len(clean)}
    (items_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Xác nhận từng chỗ nghi ngờ</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--mute:#667085;--line:#d9dde3;--acc:#2457d6;--ok:#12794b;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#10141b;--card:#181e28;--ink:#e6e9ef;--mute:#98a2b3;--line:#2b3442;--acc:#7aa2ff;--ok:#4ade80;--bad:#f87171}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.pill{background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mute)}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc)}
main{max-width:1100px;margin:0 auto;padding:16px}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:16px;padding:14px}
.item.done{border-color:var(--ok)}
.meta{color:var(--mute);font-size:13px;margin-bottom:8px;word-break:break-all}
img{max-width:100%;border:1px solid var(--line);border-radius:8px;background:#fff}
.reads{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0}
@media (max-width:700px){.reads{grid-template-columns:1fr}}
.box{border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--bg)}
.box b{display:block;font-size:12px;color:var(--mute);margin-bottom:2px}
.box div{font:14px/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.opts label{margin-right:14px;cursor:pointer}
input[type=text],textarea,select{width:100%;box-sizing:border-box;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit}
pre{white-space:pre-wrap;max-height:260px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px;font:13px/1.4 ui-monospace,Consolas,monospace}
.tag{display:inline-block;border-radius:6px;padding:0 7px;font-size:12px;border:1px solid var(--line);margin-right:6px;color:var(--mute)}
.tag.imp{color:var(--bad);border-color:var(--bad)}
h2{margin:22px 0 6px}.hint{color:var(--mute);font-size:13px}
</style></head><body>
<header><b>Xác nhận từng chỗ nghi ngờ</b><span class="pill" id="prog"></span>
<button id="exp">Xuất CSV</button><button class="sec" id="only">Chỉ hiện chưa làm</button>
<span class="pill">Tự lưu tạm trong trình duyệt</span></header>
<main>
<p class="hint">Với mỗi chỗ: nhìn <b>ảnh gốc</b> rồi chọn bên nào đọc đúng. "OCR đúng" = LLM báo nhầm. "LLM đúng" = OCR sai, LLM sửa đúng. "Cả hai sai" = điền cách đọc đúng vào ô bên dưới. "Không rõ" = ảnh quá mờ, không phân định được. Phần cuối: vài trang LLM bảo là sạch, chỉ cần cho biết có lỗi quan trọng hay không.</p>
<div id="items"></div><h2 id="autoh"></h2><div id="auto"></div><h2 id="audith"></h2><div id="audit"></div></main>
<script>
const DATA=__DATA__, COLS=__COLS__;
const FILL=["nhan","sua_thanh","co_loi_trang","ghi_chu"];
const KEY="review_items_v1:"+DATA.length+":"+(DATA[0]?DATA[0].item_id:"");
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
let only=false;
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}}
function get(r,c){return (st[r.item_id]||{})[c]||""}
function done(r){return (r.kind==="item"||r.kind==="auto")?get(r,"nhan")!=="":get(r,"co_loi_trang")!==""}
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function prog(){const n=DATA.filter(done).length;document.getElementById("prog").textContent=n+" / "+DATA.length+" đã làm"}
function autoHtml(r,i){const nh=get(r,"nhan");
 const opt=(v,t)=>`<label><input type="radio" name="n${i}" data-id="${r.item_id}" data-c="nhan" value="${v}" ${nh===v?"checked":""}> ${t}</label>`;
 return `<div class="meta"><b>#${i+1}</b> · LLM đã TỰ SỬA · ${esc(r.file)} · trang ${r.trang===""?"(ảnh)":r.trang} · <span class="tag">${esc(r.loai)}</span> <a href="${r.anh_ca_trang}" target="_blank">xem cả trang</a></div>
 <img loading="lazy" src="${r.anh}">
 <div class="reads"><div class="box"><b>OCR gốc</b><div>${esc(r.ocr)}</div></div><div class="box"><b>Sau khi LLM sửa</b><div>${esc(r.llm_doc)}</div></div></div>
 <div class="opts">${opt("dung","Sửa ĐÚNG")}${opt("sai","Sửa SAI (hoàn nguyên)")}${opt("khong_ro","Không rõ")}</div>`}
function itemHtml(r,i){const nh=get(r,"nhan");
 const opt=(v,t)=>`<label><input type="radio" name="n${i}" data-id="${r.item_id}" data-c="nhan" value="${v}" ${nh===v?"checked":""}> ${t}</label>`;
 return `<div class="meta"><b>#${i+1}</b> · ${esc(r.file)} · trang ${r.trang===""?"(ảnh)":r.trang} · <span class="tag${r.quan_trong==="1"?" imp":""}">${esc(r.loai)}${r.quan_trong==="1"?" · quan trọng":""}</span><span class="tag">LLM chắc: ${esc(r.do_chac)}</span> <a href="${r.anh_ca_trang}" target="_blank">xem cả trang</a></div>
 <img loading="lazy" src="${r.anh}">
 <div class="reads"><div class="box"><b>OCR đọc</b><div>${esc(r.ocr)}</div></div><div class="box"><b>LLM đọc từ ảnh</b><div>${esc(r.llm_doc)}</div></div></div>
 <div class="opts">${opt("ocr_dung","OCR đúng")}${opt("llm_dung","LLM đúng")}${opt("ca_hai_sai","Cả hai sai")}${opt("khong_ro","Không rõ")}</div>
 <input type="text" placeholder="Nếu cả hai sai: gõ cách đọc đúng" data-id="${r.item_id}" data-c="sua_thanh" value="${esc(get(r,"sua_thanh"))}">`}
function auditHtml(r,i){const v=get(r,"co_loi_trang");
 return `<div class="meta"><b>Trang LLM cho là sạch</b> · ${esc(r.file)} · trang ${r.trang===""?"(ảnh)":r.trang}</div>
 <a href="${r.anh_ca_trang}" target="_blank"><img loading="lazy" src="${r.anh}"></a><pre>${esc(r.ocr)}</pre>
 <label>Trang này có lỗi quan trọng (số liệu, tên riêng, đổi nghĩa)? <select data-id="${r.item_id}" data-c="co_loi_trang"><option value="">(chưa xem)</option><option value="0" ${v==="0"?"selected":""}>0 - không</option><option value="1" ${v==="1"?"selected":""}>1 - có</option></select></label>`}
function render(){const I=document.getElementById("items"),U=document.getElementById("auto"),A=document.getElementById("audit");I.innerHTML="";U.innerHTML="";A.innerHTML="";
 let na=0,nu=0;DATA.forEach((r,i)=>{if(only&&done(r))return;const d=document.createElement("div");d.className="item"+(done(r)?" done":"");
  d.innerHTML=r.kind==="item"?itemHtml(r,i):(r.kind==="auto"?autoHtml(r,i):auditHtml(r,i));
  if(r.kind==="item")I.appendChild(d);else if(r.kind==="auto"){U.appendChild(d);nu++}else{A.appendChild(d);na++}});
 document.getElementById("autoh").textContent=nu?"Kiểm tra mẫu các chỗ LLM đã tự sửa":"";
 document.getElementById("audith").textContent=na?"Kiểm tra bỏ sót: trang LLM bảo là sạch":"";
 document.querySelectorAll("[data-id]").forEach(el=>el.addEventListener("input",()=>{const id=el.dataset.id,c=el.dataset.c;
  st[id]=st[id]||{};st[id][c]=el.value;save();prog();const r=DATA.find(x=>x.item_id===id);el.closest(".item").classList.toggle("done",done(r))}));prog()}
document.getElementById("only").onclick=()=>{only=!only;render()};
document.getElementById("exp").onclick=()=>{const q=v=>'"'+String(v==null?"":v).split('"').join('""')+'"';const NL=String.fromCharCode(10);
 const lines=[COLS.map(q).join(",")];DATA.forEach(r=>{const s=st[r.item_id]||{};lines.push(COLS.map(c=>q(FILL.indexOf(c)>=0?(s[c]||""):r[c])).join(","))});
 const blob=new Blob([String.fromCharCode(0xFEFF)+lines.join(NL)],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
 a.href=URL.createObjectURL(blob);a.download="review_items_filled.csv";a.click()};
render();
</script></body></html>
"""


# ------------------------------------------------------------------ 3. tính điểm + lớp sửa lỗi tách riêng
def score_items(csv_path: str | Path | None = None, items_dir: Path | None = None, out_md: Path | None = None) -> str:
    items_dir = items_dir or ITEMS_DIR
    csv_path = Path(csv_path) if csv_path else items_dir / "review_items_filled.csv"
    if not csv_path.exists():
        raise SystemExit(f"Chưa có file kết quả đã điền: {csv_path}\nMở {items_dir / 'index.html'}, điền, bấm 'Xuất CSV', "
                         "lưu vào đường dẫn trên (hoặc --review-csv <đường dẫn>).")
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    items = [r for r in rows if r["kind"] == "item" and r["nhan"].strip()]
    audit = [r for r in rows if r["kind"] == "audit" and r["co_loi_trang"].strip() in ("0", "1")]
    lab = Counter(r["nhan"] for r in items)
    n = len(items)
    ocr_wrong = lab["llm_dung"] + lab["ca_hai_sai"]
    decided = n - lab["khong_ro"]
    o = ["# Kết quả xác nhận từng chỗ nghi ngờ", "",
         f"_Từ `{csv_path.name}` · {n}/{sum(1 for r in rows if r['kind'] == 'item')} chỗ đã xác nhận · "
         f"{len(audit)} trang kiểm tra bỏ sót_", "",
         "> Mọi con số đến từ lựa chọn **do người kiểm tra điền**. Chương trình chỉ tính toán.", "",
         "## 1. LLM báo đúng bao nhiêu", "", "| Kết luận của bạn | Số chỗ | Tỷ lệ |", "|---|---|---|"]
    for k, t in (("ocr_dung", "OCR đúng (LLM báo nhầm)"), ("llm_dung", "LLM đúng (OCR sai)"),
                 ("ca_hai_sai", "Cả hai sai"), ("khong_ro", "Không rõ")):
        o.append(f"| {t} | {lab[k]} | {lab[k] * 100 / n:.1f}% |" if n else f"| {t} | 0 | – |")
    if decided:
        lo, hi = wilson(ocr_wrong, decided)
        o += ["", f"- **Độ chính xác của lời báo (precision):** {ocr_wrong}/{decided} chỗ LLM báo là thật sự có lỗi OCR "
              f"= **{ocr_wrong * 100 / decided:.0f}%** (khoảng tin cậy 95%: {lo * 100:.0f}%–{hi * 100:.0f}%).",
              f"- Trong các chỗ OCR sai, LLM đọc **đúng** ở {lab['llm_dung']}/{ocr_wrong or 1} chỗ "
              f"({lab['llm_dung'] * 100 / max(ocr_wrong, 1):.0f}%)."]
    o += ["", "## 2. Theo loại lỗi", "", "| Loại | Số chỗ | OCR thật sự sai | Tỷ lệ |", "|---|---|---|---|"]
    byt: dict[str, list] = defaultdict(list)
    for r in items:
        byt[r["loai"] or "(không rõ)"].append(r)
    for t, rs in sorted(byt.items(), key=lambda x: -len(x[1])):
        w = sum(1 for r in rs if r["nhan"] in ("llm_dung", "ca_hai_sai"))
        d = sum(1 for r in rs if r["nhan"] != "khong_ro")
        o.append(f"| {t} | {len(rs)} | {w} | {w * 100 / d:.0f}% |" if d else f"| {t} | {len(rs)} | – | – |")
    imp = [r for r in items if r["quan_trong"] == "1"]
    if imp:
        w = sum(1 for r in imp if r["nhan"] in ("llm_dung", "ca_hai_sai"))
        o += ["", f"- Chỗ LLM đánh dấu **quan trọng** (số liệu, tên riêng): {len(imp)}, trong đó OCR thật sự sai: **{w}**."]
    if audit:
        k = sum(1 for r in audit if r["co_loi_trang"].strip() == "1")
        lo, hi = wilson(k, len(audit))
        o += ["", "## 3. LLM có bỏ sót lỗi không (kiểm tra trang LLM bảo là sạch)", "",
              f"- {k}/{len(audit)} trang LLM cho là sạch vẫn có lỗi quan trọng "
              f"(**{k * 100 / len(audit):.0f}%**, khoảng tin cậy 95%: {lo * 100:.0f}%–{hi * 100:.0f}%).",
              "- Mẫu nhỏ nên khoảng tin cậy rộng; đây chỉ là chỉ báo thô về mức bỏ sót."]
    # lớp sửa lỗi tách riêng: chỉ gồm chỗ do NGƯỜI xác nhận
    corr = []
    for r in items:
        fix = ""
        if r["nhan"] == "llm_dung":
            fix, src = r["llm_doc"], "llm_duoc_nguoi_xac_nhan"
        elif r["nhan"] == "ca_hai_sai" and r["sua_thanh"].strip():
            fix, src = r["sua_thanh"].strip(), "nguoi_nhap"
        else:
            continue
        corr.append({"trang_id": r["trang_id"], "file": r["file"], "trang": r["trang"], "ocr": r["ocr"], "sua_thanh": fix,
                     "loai": r["loai"], "nguon": src, "ghi_chu": r["ghi_chu"]})
    cf = items_dir / "confirmed_corrections.jsonl"
    items_dir.mkdir(parents=True, exist_ok=True)
    with cf.open("w", encoding="utf-8") as f:
        for c in corr:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    o += ["", "## 4. Lớp sửa lỗi (tách riêng, KHÔNG áp vào kết quả OCR)", "",
          f"- **{len(corr)}** chỗ đã được bạn xác nhận hoặc tự nhập → `{cf.name}`. File này không được dùng để sửa "
          "`data/interim/extract`; dùng hay không là quyết định ở bước sau."]
    text = "\n".join(o)
    (out_md or SCORE_MD).write_text(text, encoding="utf-8")
    return text

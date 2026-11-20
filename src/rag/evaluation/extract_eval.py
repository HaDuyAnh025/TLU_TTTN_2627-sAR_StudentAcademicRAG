"""Đánh giá, thống kê dữ liệu SAU trích xuất/OCR (chỉ ĐỌC data/interim/extract, không sửa gì).

Chạy:  python scripts/ingest.py --stage evaluate
Ra:    data/eval/extract_report.md   (báo cáo đọc được)
       data/eval/extract_stats.json  (số liệu thô)
       data/eval/extract_review/     (mẫu trang để kiểm tra tay: ảnh + text OCR; bỏ qua bằng --no-review)
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from rag.config import EVAL_DIR, RAW_DIR, load_config
from rag.ingestion.loader import FILES_DIR, out_dir
from rag.ingestion.ocr_engines import load_image_file, render_pdf_page

REPORT = EVAL_DIR / "extract_report.md"
STATS = EVAL_DIR / "extract_stats.json"
REVIEW = EVAL_DIR / "extract_review"
TRIGGER = {"low_dpi", "low_conf", "low_text", "garbled", "table_suspected", "number_mismatch"}
VN_DIAC = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
              "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ")


def pct(a: int, b: int) -> str:
    return f"{a * 100 / b:.1f}%" if b else "–"


def quantiles(xs: list[float]) -> dict:
    if not xs:
        return {}
    xs = sorted(xs)
    q = lambda p: xs[min(len(xs) - 1, int(p * (len(xs) - 1)))]
    return {"min": xs[0], "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "p95": q(0.95), "max": xs[-1],
            "mean": round(statistics.fmean(xs), 2)}


def vn_ratio(text: str) -> tuple[float, int]:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0, 0
    return sum(1 for c in letters if c in VN_DIAC) / len(letters), len(letters)


def load_docs(cfg: dict) -> list[dict]:
    """Đọc kết quả trích xuất (chỉ đọc). Nếu tên file ghi trong JSON không khớp file thật (do tên tiếng Việt bị lỗi mã hóa khi
    chuyển từ máy thuê về), dùng tên file thật khớp theo tên gốc của JSON; không sửa file JSON đã niêm phong."""
    from rag.ingestion.loader import FILES_DIR
    real = {p.stem: p.name for p in FILES_DIR.iterdir()}
    docs = []
    for jp in sorted(out_dir(cfg).glob("*.json")):
        if jp.name.startswith("_"):
            continue
        d = json.loads(jp.read_text(encoding="utf-8"))
        name = real.get(jp.stem)
        if name and d.get("file") != name:
            d["file_trong_json"], d["file"] = d.get("file"), name
        docs.append(d)
    return docs


def load_crawl() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in (RAW_DIR / "pages").glob("*/*.json")]


def evaluate(cfg: dict | None = None, review: bool = True, seed: int = 42) -> dict:
    cfg = cfg or load_config("ocr")
    docs = load_docs(cfg)
    crawl = load_crawl()
    S: dict = {"files": len(docs)}

    # ---------------------------------------------------------------- 1. tổng quan
    pages = [(d, p) for d in docs for p in d["pages"]]
    ok_pages = [(d, p) for d, p in pages if not p.get("error")]
    S["pages"] = len(pages)
    S["page_errors"] = len(pages) - len(ok_pages)
    S["route"] = dict(Counter(p["route"] for _, p in ok_pages))
    S["file_kind"] = dict(Counter(d["file_kind"] for d in docs))
    S["pipeline"] = docs[0]["pipeline"] if docs else {}
    chars_by_route: dict[str, list[int]] = defaultdict(list)
    words_total = chars_total = 0
    tables_blocks = 0
    for _, p in ok_pages:
        t = p["derived"]["text"]
        chars_by_route[p["route"]].append(len(t))
        chars_total += len(t)
        words_total += len(t.split())
        tables_blocks += sum(1 for b in p["derived"]["blocks"] if b["type"] == "table")
    S["chars_total"], S["words_total"], S["table_blocks"] = chars_total, words_total, tables_blocks
    S["chars_per_page"] = {r: quantiles(v) for r, v in chars_by_route.items()}
    S["ocr_seconds_total"] = round(sum(p.get("seconds", 0) for _, p in ok_pages if p["route"] == "ocr"), 1)
    pages_per_file = [d["page_count"] for d in docs]
    S["pages_per_file"] = quantiles(pages_per_file)
    longest = sorted(docs, key=lambda d: -d["page_count"])[:10]
    S["longest_files"] = [(d["file"][:40], d["page_count"], d.get("source", {}).get("title", "")[:70]) for d in longest]

    # ---------------------------------------------------------------- 2. theo chủ đề / năm
    topics: dict[str, Counter] = defaultdict(Counter)
    years: dict[str, Counter] = defaultdict(Counter)
    for d in docs:
        src = d.get("source") or {}
        t = src.get("topic") or "(không rõ nguồn)"
        y = (src.get("date") or "")[:4] or "(không rõ)"
        for p in d["pages"]:
            if p.get("error"):
                continue
            for bucket in (topics[t], years[y]):
                bucket["pages"] += 1
                bucket["ocr"] += p["route"] == "ocr"
                bucket["flagged"] += bool(TRIGGER & set(p["quality"]["flags"])) and p["route"] == "ocr"
        topics[t]["files"] += 1
        years[y]["files"] += 1
    S["topics"] = {k: dict(v) for k, v in topics.items()}
    S["years"] = {k: dict(v) for k, v in sorted(years.items())}

    # ---------------------------------------------------------------- 3. cờ chất lượng
    flag_c = Counter()
    flag_ocr = Counter()
    ocr_pages = [(d, p) for d, p in ok_pages if p["route"] == "ocr"]
    trig_pages = []
    combos = Counter()
    for d, p in ok_pages:
        for f in p["quality"]["flags"]:
            flag_c[f] += 1
            if p["route"] == "ocr":
                flag_ocr[f] += 1
        if p["route"] == "ocr":
            t = TRIGGER & set(p["quality"]["flags"])
            if t:
                trig_pages.append((d, p))
                combos["+".join(sorted(t))] += 1
    S["flags_all"] = dict(flag_c)
    S["flags_ocr"] = dict(flag_ocr)
    S["ocr_pages"] = len(ocr_pages)
    S["vlm_candidate_pages"] = len(trig_pages)
    S["flag_combos"] = dict(combos.most_common(12))
    S["unflagged_ocr_pages"] = len(ocr_pages) - len(trig_pages)
    ex_tokens = len(trig_pages) * 1750
    S["vlm_est_input_tokens"] = ex_tokens
    S["vlm_est_output_tokens"] = len(trig_pages) * 1000

    # ---------------------------------------------------------------- 4. độ tin cậy OCR
    confs = [p["quality"]["mean_conf"] for _, p in ocr_pages if p["quality"]["mean_conf"] is not None]
    S["ocr_conf"] = quantiles(confs)
    bins = Counter()
    for c in confs:
        bins[f"{int(c * 20) / 20:.2f}-{int(c * 20) / 20 + 0.05:.2f}"] += 1
    S["ocr_conf_hist"] = dict(sorted(bins.items()))
    S["lowest_conf_pages"] = sorted(
        [(d["file"][:36], p["page"], p["quality"]["mean_conf"], p["quality"]["flags"]) for d, p in ocr_pages
         if p["quality"]["mean_conf"] is not None], key=lambda x: x[2])[:10]
    S["ocr_words_per_page"] = quantiles([len(p["raw"]["words"]) for _, p in ocr_pages])
    S["crosscheck_run"] = sum(1 for _, p in ocr_pages if p["raw"].get("crosscheck"))
    S["rotation_applied"] = dict(Counter(p["raw"]["orientation"]["angle_ccw"] for _, p in ocr_pages))

    # ---------------------------------------------------------------- 5. trang rỗng / ít chữ
    empty = [(d["file"][:40], p["page"], p["route"], p["route_reason"]) for d, p in ok_pages if not p["derived"]["text"].strip()]
    S["empty_pages"] = empty
    S["low_text_pages"] = sum(1 for _, p in ocr_pages if "low_text" in p["quality"]["flags"])

    # ---------------------------------------------------------------- 6. bảng
    pairs = 0
    for d in docs:
        pg = d["pages"]
        for a, b in zip(pg, pg[1:]):
            if a.get("quality") and b.get("quality") and "table_maybe_continues" in a["quality"]["flags"] \
                    and "table_maybe_continued" in b["quality"]["flags"]:
                pairs += 1
    S["table_text_layer_blocks"] = tables_blocks
    S["table_suspected_ocr_pages"] = flag_ocr.get("table_suspected", 0)
    S["multi_page_table_candidates"] = pairs

    # ---------------------------------------------------------------- 7. chất lượng ngôn ngữ (dấu tiếng Việt)
    ratios = []
    low_vn = []
    for d, p in ok_pages:
        r, n = vn_ratio(p["derived"]["text"])
        if n >= 200:
            ratios.append(r)
            if r < 0.12:
                low_vn.append((d["file"][:36], p["page"], p["route"], round(r, 3), n))
    S["vn_diacritic_ratio"] = quantiles(ratios)
    S["vn_diacritic_ratio_by_route"] = {
        route: quantiles([vn_ratio(p["derived"]["text"])[0] for _, p in ok_pages
                          if p["route"] == route and vn_ratio(p["derived"]["text"])[1] >= 200])
        for route in ("text_layer", "ocr")}
    S["low_vn_pages"] = sorted(low_vn, key=lambda x: x[3])[:15]
    S["low_vn_pages_count"] = len(low_vn)

    # ---------------------------------------------------------------- 8. trùng lặp
    by_sha = defaultdict(list)
    for d in docs:
        by_sha[d["input_sha256"]].append(d["file"])
    S["duplicate_input_files"] = [v for v in by_sha.values() if len(v) > 1]
    by_text = defaultdict(set)
    for d, p in ok_pages:
        t = " ".join(p["derived"]["text"].split())
        if len(t) >= 300:
            by_text[hashlib.sha256(t.encode()).hexdigest()].add(d["file"])
    dup_text = [sorted(v) for v in by_text.values() if len(v) > 1]
    S["duplicate_page_text_groups"] = len(dup_text)

    # ---------------------------------------------------------------- 9. độ phủ so với crawl
    cr = {"pages": len(crawl), "by_topic": Counter(), "files_total": 0, "files_ok": 0, "files_failed": 0,
          "failed_ext": Counter(), "pages_all_failed": 0, "pages_no_files": 0, "pages_with_ok_file": 0,
          "dates": []}
    extracted = {d["file"] for d in docs}
    missing_in_extract = []
    for c in crawl:
        cr["by_topic"][c.get("topic", "?")] += 1
        fl = c.get("files", [])
        okf = [f for f in fl if f.get("local_path")]
        cr["files_total"] += len(fl)
        cr["files_ok"] += len(okf)
        cr["files_failed"] += len(fl) - len(okf)
        for f in fl:
            if not f.get("local_path"):
                cr["failed_ext"][Path(f["url"].split("?")[0]).suffix.lower() or "(không đuôi)"] += 1
        if not fl:
            cr["pages_no_files"] += 1
        elif not okf:
            cr["pages_all_failed"] += 1
        else:
            cr["pages_with_ok_file"] += 1
        for f in okf:
            if Path(f["local_path"]).name not in extracted:
                missing_in_extract.append(f["local_path"])
        if c.get("date"):
            cr["dates"].append(c["date"])
    cr["by_topic"] = dict(cr["by_topic"])
    cr["failed_ext"] = dict(cr["failed_ext"])
    cr["date_min"], cr["date_max"] = (min(cr["dates"]), max(cr["dates"])) if cr["dates"] else (None, None)
    del cr["dates"]
    cr["files_downloaded_but_not_extracted"] = len(missing_in_extract)
    S["crawl"] = cr

    # ---------------------------------------------------------------- 10. mẫu kiểm tra tay
    S["review_sample"] = build_review(ok_pages, seed, review)

    STATS.write_text(json.dumps(S, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    REPORT.write_text(render(S), encoding="utf-8")
    return S


def build_review(ok_pages, seed: int, export: bool) -> list[dict]:
    rng = random.Random(seed)
    groups = {
        "text_layer (không cờ)": [(d, p) for d, p in ok_pages if p["route"] == "text_layer" and not p["quality"]["flags"]],
        "OCR không cờ": [(d, p) for d, p in ok_pages if p["route"] == "ocr" and not (TRIGGER & set(p["quality"]["flags"]))],
        "OCR nghi bảng": [(d, p) for d, p in ok_pages if p["route"] == "ocr" and "table_suspected" in p["quality"]["flags"]],
        "OCR số lệch": [(d, p) for d, p in ok_pages if p["route"] == "ocr" and "number_mismatch" in p["quality"]["flags"]],
        "OCR tin cậy thấp / DPI thấp": [(d, p) for d, p in ok_pages if p["route"] == "ocr"
                                        and ({"low_conf", "low_dpi", "garbled"} & set(p["quality"]["flags"]))],
    }
    out = []
    if export:
        REVIEW.mkdir(parents=True, exist_ok=True)
    for name, items in groups.items():
        for d, p in rng.sample(items, min(6, len(items))):
            pid = d["file"].rsplit(".", 1)[0] + ("" if p["page"] is None else f"-p{p['page']}")
            rec = {"group": name, "id": pid, "file": d["file"], "page": p["page"], "flags": p["quality"]["flags"]}
            if export:
                try:
                    path = FILES_DIR / d["file"]
                    img = load_image_file(path) if d["file_kind"] == "image" else render_pdf_page(path, p["page"], 110)
                    if p["route"] == "ocr" and p["raw"]["orientation"]["angle_ccw"]:
                        img = img.rotate(p["raw"]["orientation"]["angle_ccw"], expand=True)
                    safe = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in pid)[:80]
                    img.save(REVIEW / f"{safe}.jpg", quality=80)
                    (REVIEW / f"{safe}.txt").write_text(p["derived"]["text"], encoding="utf-8")
                    rec["image"] = f"extract_review/{safe}.jpg"
                except Exception as e:  # noqa: BLE001
                    rec["export_error"] = f"{type(e).__name__}: {e}"
            out.append(rec)
    return out


def render(S: dict) -> str:
    o: list[str] = []
    A = o.append
    A("# Báo cáo đánh giá dữ liệu sau OCR")
    A("")
    A(f"_Nguồn: `data/interim/extract` · {S['files']} file · {S['pages']} trang · công cụ nền: "
      f"`{S['pipeline'].get('base_engine')}` + đối chiếu số `{S['pipeline'].get('crosscheck_engine')}` · "
      f"thiết bị: {S['pipeline'].get('device')}_")
    A("")
    A("> Báo cáo chỉ ĐỌC kết quả và thống kê; không sửa dữ liệu. Các cờ chất lượng là **dấu hiệu nghi ngờ**, "
      "không phải bằng chứng OCR sai.")
    A("")
    A("## 1. Tổng quan")
    A("")
    A("| Chỉ số | Giá trị |")
    A("|---|---|")
    A(f"| File | {S['files']} ({', '.join(f'{k}: {v}' for k, v in S['file_kind'].items())}) |")
    A(f"| Trang | {S['pages']} (lỗi: {S['page_errors']}) |")
    A(f"| Trang trích text trực tiếp | {S['route'].get('text_layer', 0)} ({pct(S['route'].get('text_layer', 0), S['pages'])}) |")
    A(f"| Trang OCR | {S['route'].get('ocr', 0)} ({pct(S['route'].get('ocr', 0), S['pages'])}) |")
    A(f"| Tổng ký tự / từ | {S['chars_total']:,} / {S['words_total']:,} |")
    A(f"| Khối bảng (trang có lớp text) | {S['table_blocks']} |")
    A(f"| Thời gian OCR cộng dồn | {S['ocr_seconds_total'] / 3600:.1f} giờ-tiến-trình |")
    q = S["pages_per_file"]
    A(f"| Số trang mỗi file | trung vị {q['median']}, trung bình {q['mean']}, p95 {q['p95']}, tối đa {q['max']} |")
    for route, cq in S["chars_per_page"].items():
        A(f"| Ký tự/trang ({route}) | trung vị {cq['median']}, p25 {cq['p25']}, p75 {cq['p75']}, tối đa {cq['max']} |")
    A("")
    A("**10 file dài nhất:**")
    A("")
    A("| File | Số trang | Tiêu đề nguồn |")
    A("|---|---|---|")
    for f, n, t in S["longest_files"]:
        A(f"| `{f}` | {n} | {t} |")
    A("")
    A("## 2. Theo chủ đề và năm")
    A("")
    A("| Chủ đề | File | Trang | Trang OCR | OCR bị gắn cờ cần VLM |")
    A("|---|---|---|---|---|")
    for k, v in sorted(S["topics"].items(), key=lambda x: -x[1].get("pages", 0)):
        A(f"| {k} | {v.get('files', 0)} | {v.get('pages', 0)} | {v.get('ocr', 0)} | {v.get('flagged', 0)} ({pct(v.get('flagged', 0), v.get('ocr', 0))}) |")
    A("")
    A("| Năm (ngày đăng thông báo) | File | Trang | Trang OCR | OCR bị gắn cờ |")
    A("|---|---|---|---|---|")
    for k, v in S["years"].items():
        A(f"| {k} | {v.get('files', 0)} | {v.get('pages', 0)} | {v.get('ocr', 0)} | {v.get('flagged', 0)} |")
    A("")
    A("## 3. Cờ chất lượng")
    A("")
    A(f"- Trang OCR: **{S['ocr_pages']}**, trong đó **{S['vlm_candidate_pages']} ({pct(S['vlm_candidate_pages'], S['ocr_pages'])})** "
      f"mang ít nhất một cờ nghi ngờ (ứng viên cho VLM), **{S['unflagged_ocr_pages']}** không cờ.")
    A("")
    A("| Cờ | Mọi trang | Trong trang OCR | Ý nghĩa |")
    A("|---|---|---|---|")
    meaning = {"table_suspected": "nhiều dòng có khoảng cột lớn → nghi bảng, cấu trúc cột chưa chắc đúng",
               "number_mismatch": "chuỗi số giữa hai công cụ OCR khác nhau → nghi sai chữ số",
               "low_conf": "độ tin cậy OCR trung bình thấp", "low_dpi": "ảnh scan độ phân giải thấp",
               "low_text": "đọc được rất ít chữ", "garbled": "nhiều ký tự lạ",
               "table_maybe_continues": "bảng chạm đáy trang (có thể sang trang sau)",
               "table_maybe_continued": "bảng bắt đầu sát đầu trang (có thể tiếp nối trang trước)",
               "embedded_ocr_text": "trang scan có sẵn lớp OCR của tác giả file, chất lượng chưa rõ",
               "few_text": "trang ít chữ không phải ảnh"}
    for f, n in sorted(S["flags_all"].items(), key=lambda x: -x[1]):
        A(f"| `{f}` | {n} | {S['flags_ocr'].get(f, 0)} | {meaning.get(f, '')} |")
    A("")
    A("**Tổ hợp cờ phổ biến nhất (trên trang OCR):**")
    A("")
    for k, v in S["flag_combos"].items():
        A(f"- `{k}`: {v}")
    A("")
    A(f"**Ước tính khối lượng nếu gửi VLM cho toàn bộ ứng viên:** {S['vlm_candidate_pages']} trang ≈ "
      f"{S['vlm_est_input_tokens']:,} token vào và ≈ {S['vlm_est_output_tokens']:,} token ra "
      "(ước lượng thô 1750 vào / 1000 ra mỗi trang; chưa nhân giá).")
    A("")
    A("## 4. Độ tin cậy OCR")
    A("")
    c = S["ocr_conf"]
    A(f"Độ tin cậy trung bình mỗi trang (VietOCR): trung vị **{c.get('median')}**, p25 {c.get('p25')}, p75 {c.get('p75')}, "
      f"min {c.get('min')}. (Điểm tin cậy của mô hình, không phải độ chính xác thật.)")
    A("")
    A("| Khoảng | Số trang |")
    A("|---|---|")
    for k, v in S["ocr_conf_hist"].items():
        A(f"| {k} | {v} |")
    A("")
    A("**10 trang tin cậy thấp nhất:**")
    A("")
    A("| File | Trang | Tin cậy | Cờ |")
    A("|---|---|---|---|")
    for f, pg, cf, fl in S["lowest_conf_pages"]:
        A(f"| `{f}` | {pg} | {cf} | {', '.join(fl)} |")
    A("")
    A(f"Hướng trang được xoay thêm (độ, ngược chiều kim đồng hồ): {S['rotation_applied']}. "
      f"Số trang có đối chiếu số bằng công cụ thứ hai: {S['crosscheck_run']}.")
    A("")
    A("## 5. Trang rỗng và ít chữ")
    A("")
    A(f"- Trang không có chữ nào: **{len(S['empty_pages'])}**; trang OCR bị cờ `low_text`: **{S['low_text_pages']}**.")
    for f, pg, route, reason in S["empty_pages"][:10]:
        A(f"  - `{f}` trang {pg} ({route}, {reason})")
    A("")
    A("## 6. Bảng")
    A("")
    A(f"- Khối bảng tách từ lớp text PDF: **{S['table_text_layer_blocks']}** (cấu trúc do PyMuPDF; cần kiểm tra mẫu).")
    A(f"- Trang OCR nghi có bảng (`table_suspected`): **{S['table_suspected_ocr_pages']}**. Với các trang này OCR chỉ cho "
      "dòng chữ có dấu ` | ` gợi ý cột, **chưa có cấu trúc bảng**.")
    A(f"- Cặp trang liên tiếp nghi là bảng nhiều trang: **{S['multi_page_table_candidates']}** (mới gắn cờ, chưa nối).")
    A("")
    A("## 7. Chất lượng ngôn ngữ (tỷ lệ chữ có dấu tiếng Việt)")
    A("")
    A("Văn bản tiếng Việt thông thường có khoảng 30–40% chữ cái mang dấu. Tỷ lệ rất thấp có thể là trang tiếng Anh, "
      "trang toàn số liệu, hoặc OCR mất dấu.")
    A("")
    for route, qv in S["vn_diacritic_ratio_by_route"].items():
        if qv:
            A(f"- {route}: trung vị {qv['median']:.3f}, p25 {qv['p25']:.3f}, p75 {qv['p75']:.3f}")
    A(f"- Trang (≥200 chữ cái) có tỷ lệ dưới 0,12: **{S['low_vn_pages_count']}**. 15 trang thấp nhất:")
    A("")
    A("| File | Trang | Luồng | Tỷ lệ | Số chữ cái |")
    A("|---|---|---|---|---|")
    for f, pg, route, r, n in S["low_vn_pages"]:
        A(f"| `{f}` | {pg} | {route} | {r} | {n} |")
    A("")
    A("## 8. Trùng lặp")
    A("")
    A(f"- Nhóm file có nội dung gốc giống hệt nhau (cùng mã băm): **{len(S['duplicate_input_files'])}**.")
    for g in S["duplicate_input_files"][:5]:
        A(f"  - {', '.join('`' + x[:30] + '`' for x in g)}")
    A(f"- Nhóm trang có cùng văn bản (≥300 ký tự) ở nhiều file khác nhau: **{S['duplicate_page_text_groups']}**.")
    A("")
    A("## 9. Độ phủ so với dữ liệu crawl")
    A("")
    cr = S["crawl"]
    A(f"- Trang crawl: **{cr['pages']}** (ngày đăng từ {cr['date_min']} đến {cr['date_max']}).")
    A(f"- File đính kèm: **{cr['files_total']}**, tải được **{cr['files_ok']}**, **không tải được {cr['files_failed']}** "
      f"(theo đuôi: {cr['failed_ext']}).")
    A(f"- Trang crawl có ít nhất 1 file đã xử lý: **{cr['pages_with_ok_file']}**; không có file đính kèm: **{cr['pages_no_files']}**; "
      f"toàn bộ file đều lỗi: **{cr['pages_all_failed']}**.")
    A(f"- File đã tải nhưng chưa được trích xuất: **{cr['files_downloaded_but_not_extracted']}**.")
    A("")
    A("| Chủ đề (crawl) | Số trang crawl |")
    A("|---|---|")
    for k, v in sorted(cr["by_topic"].items(), key=lambda x: -x[1]):
        A(f"| {k} | {v} |")
    A("")
    A("Các chủ đề không xuất hiện trong bảng trên (ví dụ *môn thay thế*) = **không có dữ liệu** trong tập đã crawl.")
    A("")
    A("## 10. Mẫu để kiểm tra bằng mắt")
    A("")
    A("Mẫu ngẫu nhiên (cố định hạt giống), mỗi nhóm tối đa 6 trang. Ảnh và text OCR nằm ở `data/eval/extract_review/`: "
      "mở ảnh, đối chiếu với file `.txt` cùng tên. Đây là cách duy nhất để biết **độ chính xác thật** của OCR.")
    A("")
    A("| Nhóm | Trang | Cờ | Ảnh |")
    A("|---|---|---|---|")
    for r in S["review_sample"]:
        A(f"| {r['group']} | `{r['id'][:50]}` | {', '.join(r['flags']) or '–'} | {r.get('image', r.get('export_error', ''))} |")
    A("")
    return "\n".join(o)

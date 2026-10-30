"""OCR các PDF dạng ảnh scan (pdf_class = scan trong extract/classify_log.csv).

Đọc danh sách scan từ bước 4 của extract_files.py, OCR từng trang bằng Tesseract (tiếng Việt `vie`),
ghi văn bản vào extract/text/<file_key>.txt và cập nhật extract/extract_log.csv, nên bước `merge` và
`report` của extract_files.py dùng được ngay.

Chạy:
    python ocr_scans.py check                         # kiểm tra Tesseract + gói tiếng Việt
    python ocr_scans.py setup-lang                    # tải vie.traineddata vào extract/tessdata/
    python ocr_scans.py list                          # liệt kê 71 file scan theo thứ tự ưu tiên
    python ocr_scans.py run --limit-files 1 --max-pages 2     # chạy thử
    python ocr_scans.py run --category hoc_phi ke_hoach_dao_tao quy_che
    python ocr_scans.py run --merge                   # OCR hết rồi gắn lại bản ghi + báo cáo

Đặc điểm:
    - Chạy song song nhiều tiến trình (--workers), mỗi trang một tác vụ.
    - Cache từng trang trong extract/ocr/<file_key>/pNNNN.json: ngắt (Ctrl+C) rồi chạy lại sẽ tiếp tục.
    - Ghi độ tin cậy trung bình từng trang vào extract/ocr_log.csv; trang dưới 60 nên đọc lại bằng mắt.
    - Chỉ ghi vào text/ và extract_log.csv khi OCR đủ MỌI trang của file (--max-pages chỉ để chạy thử).
"""
import argparse
import csv
import json
import os
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import extract_files as ef

DEFAULT_ORDER = ["hoc_phi", "ke_hoach_dao_tao", "quy_che", "thong_tin_sinh_vien", "chuong_trinh_dao_tao"]
LOW_CONF = 60
ROT_THRESH = 70        # trang tin cậy dưới mức này mới kiểm tra hướng xoay
OCR_LOG_FIELDS = ["file_key", "page", "n_words", "n_chars", "mean_conf", "rotate", "seconds", "dpi", "lang", "psm"]
LANG_URL = "https://github.com/tesseract-ocr/tessdata_{variant}/raw/main/{lang}.traineddata"

_STD_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]
INSTALL_HELP = """Chưa tìm thấy Tesseract. Cài đặt:
  1. winget install --id UB-Mannheim.TesseractOCR -e        (cần quyền quản trị)
     hoặc tải bộ cài: https://github.com/UB-Mannheim/tesseract/wiki
  2. pip install pytesseract
  3. python ocr_scans.py setup-lang                          (tải gói tiếng Việt về extract/tessdata/)
  4. python ocr_scans.py check
Nếu Tesseract cài ở chỗ lạ: dùng --tesseract "đường\\dẫn\\tesseract.exe" hoặc biến môi trường TESSERACT_CMD."""


def ocr_dir():
    return ef.EXT / "ocr"


def ocr_log_path():
    return ef.EXT / "ocr_log.csv"


def local_tessdata():
    return ef.EXT / "tessdata"


# ----------------------------------------------------------------------------- Tesseract
def find_tesseract(cmd=None):
    for c in (cmd, os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"), *_STD_PATHS):
        if c and Path(c).exists():
            return str(c)
    return None


def setup_engine(cmd=None, tessdata=None):
    """Trỏ pytesseract tới tesseract.exe và thư mục tessdata. Trả về (exe, tessdata)."""
    import pytesseract
    exe = find_tesseract(cmd)
    if not exe:
        raise RuntimeError(INSTALL_HELP)
    pytesseract.pytesseract.tesseract_cmd = exe
    td = tessdata or (str(local_tessdata()) if (local_tessdata() / "vie.traineddata").exists() else None)
    if td:
        os.environ["TESSDATA_PREFIX"] = str(td)
    return exe, td


def check(cmd=None, tessdata=None, lang="vie"):
    """In trạng thái môi trường OCR. Trả về True nếu sẵn sàng."""
    try:
        import pytesseract
    except ImportError:
        print("pytesseract : CHƯA CÀI  ->  pip install pytesseract")
        return False
    print("pytesseract : có")
    try:
        exe, td = setup_engine(cmd, tessdata)
    except RuntimeError as e:
        print(e)
        return False
    print("tesseract   :", exe)
    print("tessdata    :", td or "(mặc định của Tesseract)")
    try:
        print("phiên bản   :", pytesseract.get_tesseract_version())
        langs = pytesseract.get_languages(config="")
    except Exception as e:  # noqa: BLE001
        print("không chạy được Tesseract:", e)
        return False
    print("ngôn ngữ    :", ", ".join(langs))
    if lang not in langs:
        print(f"THIẾU gói '{lang}'  ->  python ocr_scans.py setup-lang")
        return False
    return True


def setup_lang(lang="vie", variant="best"):
    """Tải <lang>.traineddata vào extract/tessdata/ (không cần quyền quản trị)."""
    dest = local_tessdata() / f"{lang}.traineddata"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"Đã có {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    url = LANG_URL.format(variant=variant, lang=lang)
    print("Tải", url)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ef.UA}), timeout=120) as r:
        data = r.read()
    if len(data) < 1_000_000:
        raise RuntimeError(f"File tải về quá nhỏ ({len(data)} byte), có thể không phải gói ngôn ngữ")
    dest.write_bytes(data)
    print(f"Đã lưu {dest} ({len(data) / 1e6:.1f} MB)")
    return dest


# ----------------------------------------------------------------------------- OCR một trang
def n_pages_of(pdf_path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page(pdf_path, index, dpi):
    """Dựng trang PDF thành ảnh xám."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdf[index].render(scale=dpi / 72).to_pil().convert("L")
    finally:
        pdf.close()


def ocr_image(img, lang="vie", psm=3):
    """OCR một ảnh. Trả về chữ (giữ ngắt dòng / đoạn) và độ tin cậy trung bình."""
    import pytesseract
    from pytesseract import Output
    d = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm}", output_type=Output.DICT)
    lines, order, confs = {}, [], []
    for i, w in enumerate(d["text"]):
        w = (w or "").strip()
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not w or conf < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(w)
        confs.append(conf)
    out, prev = [], None
    for key in order:
        if prev is not None and key[:2] != prev[:2]:
            out.append("")                       # đoạn / khối mới
        out.append(" ".join(lines[key]))
        prev = key
    return {"text": "\n".join(out).strip(), "n_words": len(confs),
            "mean_conf": round(sum(confs) / len(confs), 1) if confs else 0.0}


def _init_worker(cmd, tessdata):
    os.environ["OMP_THREAD_LIMIT"] = "1"        # mỗi tiến trình 1 luồng, tránh tranh CPU
    setup_engine(cmd, tessdata)


def detect_rotation(img):
    """Góc cần xoay (theo chiều kim đồng hồ) để trang đứng thẳng: 0, 90, 180 hoặc 270.
    Dùng OSD của Tesseract (cần osd.traineddata). Lỗi hoặc quá ít chữ thì trả về 0."""
    try:
        import pytesseract
        from pytesseract import Output
        return int(pytesseract.image_to_osd(img, config="--psm 0", output_type=Output.DICT).get("rotate", 0))
    except Exception:  # noqa: BLE001
        return 0


def _page_task(args):
    """OCR một trang. Trang tin cậy thấp thì kiểm tra hướng; nếu xoay lại cho kết quả tốt hơn thì dùng bản xoay.
    Trang đã có trong cache nhưng chưa kiểm tra hướng được dùng lại kết quả cũ, không OCR hai lần."""
    key, path, idx, dpi, lang, psm, cache_path, auto_rotate = args
    t0 = time.time()
    cp = Path(cache_path)
    prev = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else None
    img = render_page(path, idx, dpi)
    res = prev if prev is not None else ocr_image(img, lang, psm)
    res.setdefault("rotate", 0)
    if auto_rotate and res["mean_conf"] < ROT_THRESH:
        angle = detect_rotation(img)
        if angle:
            cand = ocr_image(img.rotate(-angle, expand=True), lang, psm)
            if cand["mean_conf"] > res["mean_conf"] + 5:
                res = dict(cand, rotate=angle)
    if auto_rotate and res["mean_conf"] < LOW_CONF and not res.get("rot_full"):
        # OSD không nhận ra hướng (trang toàn đường kẻ bảng, ít chữ): thử lần lượt các góc còn lại, giữ bản tốt nhất
        for angle in (180, 90, 270):
            if angle == res.get("rotate"):
                continue
            cand = ocr_image(img.rotate(-angle, expand=True), lang, psm)
            if cand["mean_conf"] > res["mean_conf"] + 5:
                res = dict(cand, rotate=angle)
        res["rot_full"] = True
    res.update(file_key=key, page=idx + 1, dpi=dpi, lang=lang, psm=psm, rot_checked=bool(auto_rotate),
               seconds=round(time.time() - t0 + (prev or {}).get("seconds", 0), 1))
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return key, idx, res


def _needs_ocr(key, idx, auto_rotate):
    p = page_cache(key, idx)
    if not p.exists():
        return True
    if not auto_rotate:
        return False
    d = json.loads(p.read_text(encoding="utf-8"))
    conf = d.get("mean_conf", 100)
    return ((not d.get("rot_checked")) and conf < ROT_THRESH) or (conf < LOW_CONF and not d.get("rot_full"))


# ----------------------------------------------------------------------------- chọn file, gom kết quả
def find_scans(categories=None, file_keys=None, force=False):
    """Danh sách file scan theo thứ tự ưu tiên (nhóm nhỏ trước, file ít trang trước).
    force=True (cùng file_keys): OCR cả file không phải scan, vd. PDF có lớp chữ bị mã hóa font sai."""
    mf = {r["file_key"]: r for r in ef.load_manifest()}
    rows = []
    for r in ef.read_classify_log():
        if r["pdf_class"] != "scan" and not (force and file_keys and r["file_key"] in file_keys):
            continue
        m = mf.get(r["file_key"], {})
        cat = m.get("category", "")
        if categories and cat not in categories:
            continue
        if file_keys and r["file_key"] not in file_keys:
            continue
        pdf = ef.RAW / f"{r['file_key']}.pdf"
        if not pdf.exists():
            continue
        prio = DEFAULT_ORDER.index(cat) if cat in DEFAULT_ORDER else len(DEFAULT_ORDER)
        rows.append({"file_key": r["file_key"], "record_id": m.get("record_id", ""), "category": cat,
                     "n_pages": int(r["n_pages"]), "path": pdf, "prio": prio})
    rows.sort(key=lambda x: (x["prio"], x["n_pages"], x["file_key"]))
    return rows


def page_cache(key, idx):
    return ocr_dir() / key / f"p{idx + 1:04d}.json"


def read_cached(key, n_pages):
    """Trả về danh sách kết quả từng trang, hoặc None nếu thiếu trang."""
    out = []
    for i in range(n_pages):
        p = page_cache(key, i)
        if not p.exists():
            return None
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def assemble(key, n_pages, dpi, lang):
    """Gộp các trang đã OCR thành văn bản của file; ghi text/ và extract_log.csv."""
    pages = read_cached(key, n_pages)
    if pages is None:
        return None
    text = "\n\n".join(p["text"] for p in pages if p["text"]).strip()
    confs = [p["mean_conf"] for p in pages if p["n_words"]]
    mean = sum(confs) / len(confs) if confs else 0.0
    low = sum(1 for p in pages if p["n_words"] and p["mean_conf"] < LOW_CONF)
    rot = sum(1 for p in pages if p.get("rotate"))
    status = "ok" if text else "empty"
    if text:
        ef.TEXT.mkdir(parents=True, exist_ok=True)
        (ef.TEXT / f"{key}.txt").write_text(text, encoding="utf-8")
    row = {"file_key": key, "ext": "pdf", "status": status, "method": "pdf_ocr", "n_pages": n_pages,
           "n_chars": len(text), "chars_per_page": round(len(text) / n_pages) if n_pages else 0, "n_tables": 0,
           "note": f"OCR tesseract {lang} dpi={dpi}; tin cậy TB {mean:.0f}; {low} trang < {LOW_CONF}; {rot} trang tự xoay" if text
           else "OCR không đọc được chữ nào"}
    ef._upsert_log(ef.EX_LOG, ef.EX_FIELDS, [row])
    return row


def write_ocr_log():
    rows = []
    if ocr_dir().exists():
        for p in sorted(ocr_dir().glob("*/p*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            rows.append({"file_key": d["file_key"], "page": d["page"], "n_words": d["n_words"], "n_chars": len(d["text"]),
                         "mean_conf": d["mean_conf"], "rotate": d.get("rotate", 0), "seconds": d.get("seconds", ""),
                         "dpi": d.get("dpi", ""),
                         "lang": d.get("lang", ""), "psm": d.get("psm", "")})
    ef._write_csv(ocr_log_path(), rows, OCR_LOG_FIELDS)
    return rows


# ----------------------------------------------------------------------------- chạy
def run(categories=None, file_keys=None, limit_files=None, max_pages=None, workers=None, dpi=250, lang="vie",
        psm=3, cmd=None, tessdata=None, verbose=True, auto_rotate=True, force=False):
    scans = find_scans(categories, file_keys, force)
    if limit_files:
        scans = scans[:limit_files]
    if not scans:
        print("Không có file scan nào khớp điều kiện.")
        return []
    workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 2)

    tasks, need, done_files = [], {}, []
    for s in scans:
        n = s["n_pages"] if not max_pages else min(max_pages, s["n_pages"])
        todo = [i for i in range(n) if _needs_ocr(s["file_key"], i, auto_rotate)]
        need[s["file_key"]] = len(todo)
        tasks += [(s["file_key"], str(s["path"]), i, dpi, lang, psm, str(page_cache(s["file_key"], i)), auto_rotate)
                  for i in todo]
        if not todo and read_cached(s["file_key"], s["n_pages"]) is not None:
            done_files.append(s["file_key"])
    total_pages = sum(s["n_pages"] for s in scans)
    if verbose:
        print(f"{len(scans)} file, {total_pages} trang | trang cần OCR lần này: {len(tasks)} | workers: {workers} | dpi {dpi} | lang {lang}")

    results, t0 = [], time.time()
    finished = 0

    def on_page(key, res):
        nonlocal finished
        finished += 1
        need[key] -= 1
        if verbose and (finished % 10 == 0 or need[key] == 0):
            el = time.time() - t0
            eta = el / finished * (len(tasks) - finished)
            print(f"  [{finished}/{len(tasks)}] {key[:40]} trang {res['page']}: tin cậy {res['mean_conf']:.0f}, "
                  f"{res['n_words']} từ | đã {el / 60:.1f} phút, còn ~{eta / 60:.1f} phút")

    if tasks:
        if workers <= 1:
            setup_engine(cmd, tessdata)
            for a in tasks:
                key, _, res = _page_task(a)
                on_page(key, res)
        else:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(cmd, tessdata)) as ex:
                futs = [ex.submit(_page_task, a) for a in tasks]
                try:
                    for f in as_completed(futs):
                        key, _, res = f.result()
                        on_page(key, res)
                except KeyboardInterrupt:
                    print("Đã ngắt. Các trang đã OCR được giữ trong cache; chạy lại để tiếp tục.")
                    for f in futs:
                        f.cancel()
                    raise

    for s in scans:
        row = assemble(s["file_key"], s["n_pages"], dpi, lang)
        if row:
            results.append(row)
            if verbose:
                print(f"  -> {s['record_id']} | {s['file_key'][:38]}: {row['status']}, {row['n_chars']} ký tự | {row['note']}")
        elif verbose:
            print(f"  .. {s['record_id']} | {s['file_key'][:38]}: mới OCR một phần ({s['n_pages']} trang), chưa ghi kết quả")
    write_ocr_log()
    return results


def main():
    ap = argparse.ArgumentParser(description="OCR các PDF dạng ảnh scan")
    ap.add_argument("cmd", choices=["check", "setup-lang", "list", "run"])
    ap.add_argument("--category", nargs="+", help="chỉ OCR các nhóm này (vd: hoc_phi quy_che)")
    ap.add_argument("--file-key", nargs="+", help="chỉ OCR các file_key này")
    ap.add_argument("--limit-files", type=int, help="chỉ OCR N file đầu theo thứ tự ưu tiên")
    ap.add_argument("--max-pages", type=int, help="chỉ OCR N trang đầu mỗi file (chạy thử)")
    ap.add_argument("--workers", type=int, help="số tiến trình song song (mặc định: số CPU - 2)")
    ap.add_argument("--dpi", type=int, default=250)
    ap.add_argument("--lang", default="vie")
    ap.add_argument("--psm", type=int, default=3, help="chế độ phân đoạn trang của Tesseract (mặc định 3)")
    ap.add_argument("--tesseract", help="đường dẫn tesseract.exe")
    ap.add_argument("--tessdata", help="thư mục chứa vie.traineddata")
    ap.add_argument("--variant", default="best", choices=["best", "fast"], help="bản gói ngôn ngữ khi setup-lang")
    ap.add_argument("--no-rotate", action="store_true", help="tắt tự động xoay trang bị lật / nằm ngang")
    ap.add_argument("--force", action="store_true", help="với --file-key: OCR cả file không phải scan (lớp chữ hỏng)")
    ap.add_argument("--merge", action="store_true", help="sau khi OCR: chạy merge + report của extract_files")
    a = ap.parse_args()

    if a.cmd == "check":
        sys.exit(0 if check(a.tesseract, a.tessdata, a.lang) else 1)
    if a.cmd == "setup-lang":
        setup_lang(a.lang, a.variant)
        setup_lang("osd", a.variant)          # nhận dạng hướng trang (trang bị lật / nằm ngang)
        return
    if a.cmd == "list":
        scans = find_scans(a.category, a.file_key, a.force)
        print(f"{'#':>2} {'nhóm':<22} {'bản ghi':<9} {'trang':>5}  {'đã OCR':<7} file_key")
        for i, s in enumerate(scans, 1):
            done = "có" if read_cached(s["file_key"], s["n_pages"]) is not None else "chưa"
            print(f"{i:>2} {s['category']:<22} {s['record_id']:<9} {s['n_pages']:>5}  {done:<7} {s['file_key'][:46]}")
        print(f"Tổng: {len(scans)} file, {sum(s['n_pages'] for s in scans)} trang")
        return
    try:
        run(a.category, a.file_key, a.limit_files, a.max_pages, a.workers, a.dpi, a.lang, a.psm, a.tesseract, a.tessdata,
            auto_rotate=not a.no_rotate, force=a.force)
    except RuntimeError as e:
        sys.exit(str(e))
    if a.merge:
        _, stat = ef.merge()
        rep = ef.quality_report()
        print("Bản ghi theo trạng thái trích xuất:", stat)
        print("Trích xuất:", rep["extract"])


if __name__ == "__main__":
    main()

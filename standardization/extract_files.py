"""Trích xuất chữ từ file đính kèm (PDF / Google Sheets) của crawl_v2.

Quy trình (khớp từng bước):
    0. Chuẩn bị     pdfplumber (đọc PDF), openpyxl (đọc Sheets); OCR chỉ khi cần
    1. list         Quét data/crawl_v2.json -> extract/manifest.csv
    2. probe        Thử 3 file: 1 PDF, 1 Sheets, 1 thư mục -> extract/probe_log.csv
    3. download     Tải hàng loạt, cache theo file_id        -> extract/raw_files/ + download_log.csv
    4. classify     Phân loại PDF: pdf_text hay scan         -> extract/classify_log.csv
    5. extract      Trích xuất chữ                           -> extract/text/ + extract_log.csv
    6. merge        Gắn lại bản ghi                          -> data/crawl_v2_extracted.json
    7. report       Kiểm tra chất lượng                      -> extract/quality_report.md
    8. (bàn giao)   normalize.py rồi chunking trên `extracted_text`

Chạy:
    python extract_files.py list
    python extract_files.py probe
    python extract_files.py download
    python extract_files.py classify
    python extract_files.py extract
    python extract_files.py merge
    python extract_files.py report
    python extract_files.py all          # chạy 1 -> 7 (bỏ qua probe)

Nguyên tắc: chỉ đọc (GET), nghỉ giữa các request, cache theo file_key nên chạy lại không tải lại.
File gốc data/crawl_v2.json không bị sửa.
"""
import argparse
import csv
import datetime
import hashlib
import html as htmllib
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "crawl_v2.json"
OUT = ROOT / "data" / "crawl_v2_extracted.json"
EXT = ROOT / "extract"
RAW = EXT / "raw_files"
TEXT = EXT / "text"
MANIFEST = EXT / "manifest.csv"
PROBE_LOG = EXT / "probe_log.csv"
DL_LOG = EXT / "download_log.csv"
CLS_LOG = EXT / "classify_log.csv"
EX_LOG = EXT / "extract_log.csv"
REPORT = EXT / "quality_report.md"

UA = "Mozilla/5.0 (research crawler; contact: nguyenvanphuc10124@gmail.com)"
MAX_BYTES = 50 * 1024 * 1024        # bỏ qua file lớn hơn 50 MB
MIN_CHARS_PER_PAGE = 30             # ít hơn mức này thì coi là bản scan (ảnh)

MANIFEST_FIELDS = ["record_id", "category", "content_type", "link_name", "kind", "file_id", "file_key",
                   "parent", "url", "url_norm", "download_url", "status"]
PROBE_FIELDS = ["kind", "file_key", "status", "detail"]
DL_FIELDS = ["file_key", "kind", "status", "path", "bytes", "error", "time"]
CLS_FIELDS = ["file_key", "n_pages", "n_chars", "chars_per_page", "pdf_class", "error"]
EX_FIELDS = ["file_key", "ext", "status", "method", "n_pages", "n_chars", "chars_per_page", "n_tables", "note"]


# ----------------------------------------------------------------------------- phân loại link
_LINK_PATTERNS = [
    ("drive-file", re.compile(r"drive\.google\.com/file/d/([\w-]+)")),
    ("drive-folder", re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]+)")),
    ("google-sheet", re.compile(r"docs\.google\.com/spreadsheets/d/([\w-]+)")),
    ("google-doc", re.compile(r"docs\.google\.com/document/d/([\w-]+)")),
]
_DOWNLOAD_URL = {
    "drive-file": lambda i: f"https://drive.usercontent.google.com/download?id={i}&export=download&confirm=t",
    "google-sheet": lambda i: f"https://docs.google.com/spreadsheets/d/{i}/export?format=xlsx",
    "google-doc": lambda i: f"https://docs.google.com/document/d/{i}/export?format=pdf",
    "drive-folder": lambda i: "",      # thư mục: không có 1 file để tải
}
_NORM_URL = {
    "drive-file": lambda i: f"https://drive.google.com/file/d/{i}/preview",
    "drive-folder": lambda i: f"https://drive.google.com/drive/folders/{i}",
    "google-sheet": lambda i: f"https://docs.google.com/spreadsheets/d/{i}",
    "google-doc": lambda i: f"https://docs.google.com/document/d/{i}",
}


def classify_url(url):
    """Trả về (kind, file_id, url_chuẩn_hóa, url_tải); (None, None, None, None) nếu không phải file đính kèm."""
    url = (url or "").strip()
    for kind, rx in _LINK_PATTERNS:
        m = rx.search(url)
        if m:
            fid = m.group(1)
            return kind, fid, _NORM_URL[kind](fid), _DOWNLOAD_URL[kind](fid)
    if url.startswith("https://media-cms.thanglong.edu.vn/"):
        fid = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return "media-cms", fid, url, url
    return None, None, None, None


# ----------------------------------------------------------------------------- tiện ích
def ensure_dirs():
    for d in (RAW, TEXT):
        d.mkdir(parents=True, exist_ok=True)


def _read_csv(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows, fields):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _upsert_log(path, fields, new_rows):
    """Log cộng dồn theo file_key: lần chạy sau cập nhật dòng cũ, không mất dòng của lần trước."""
    cur = {r["file_key"]: r for r in _read_csv(path)}
    for r in new_rows:
        cur[r["file_key"]] = {k: r.get(k, "") for k in fields}
    _write_csv(path, list(cur.values()), fields)
    return cur


def load_records(path=None):
    return json.loads(Path(path or SRC).read_text(encoding="utf-8"))


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------- bước 1: danh sách tệp
def build_manifest(records):
    """Mỗi dòng = một (bản ghi, file đính kèm). Cùng một file ở nhiều bản ghi vẫn dùng chung file_key."""
    rows, seen = [], set()
    for r in records:
        for link in r.get("links", []):
            kind, fid, norm, dl = classify_url(link.get("url", ""))
            if not kind:
                continue
            key = f"{kind}_{fid}"
            if (r["id"], key) in seen:
                continue
            seen.add((r["id"], key))
            rows.append({
                "record_id": r["id"], "category": r.get("category", ""), "content_type": r.get("content_type", ""),
                "link_name": link.get("name", ""), "kind": kind, "file_id": fid, "file_key": key, "parent": "",
                "url": link["url"].strip(), "url_norm": norm, "download_url": dl, "status": "pending",
            })
    return rows


def save_manifest(rows):
    _write_csv(MANIFEST, rows, MANIFEST_FIELDS)
    return MANIFEST


def load_manifest():
    return _read_csv(MANIFEST)


def sync_manifest_status():
    """Ghi trạng thái tải mới nhất (từ download_log) vào cột `status` của manifest."""
    rows = load_manifest()
    dl = {r["file_key"]: r["status"] for r in _read_csv(DL_LOG)}
    for r in rows:
        r["status"] = dl.get(r["file_key"], r.get("status") or "pending")
    save_manifest(rows)
    return rows


# ----------------------------------------------------------------------------- tải file
def _sniff(data):
    """Nhận dạng loại file thật từ nội dung (Drive có thể trả trang HTML thay vì file)."""
    head = data[:16]
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return ".zip"
        if any(n.startswith("xl/") for n in names):
            return ".xlsx"
        if any(n.startswith("word/") for n in names):
            return ".docx"
        if any(n.startswith("ppt/") for n in names):
            return ".pptx"
        return ".zip"
    if head.lstrip().lower().startswith((b"<!doc", b"<html")):
        return "html"
    return None


def _fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_BYTES + 1)


def _cached_path(file_key):
    hits = sorted(RAW.glob(f"{file_key}.*")) if RAW.exists() else []
    return hits[0] if hits else None


def download_one(m):
    """Tải một file (có cache). Trả về dòng log."""
    key = m["file_key"]
    hit = _cached_path(key)
    if hit:
        return {"file_key": key, "kind": m["kind"], "status": "ok", "path": str(hit.relative_to(ROOT)),
                "bytes": hit.stat().st_size, "error": "cache", "time": _now(), "_network": False}
    row = {"file_key": key, "kind": m["kind"], "status": "error", "path": "", "bytes": 0, "error": "",
           "time": _now(), "_network": True}
    try:
        data = _fetch(m["download_url"])
        if len(data) > MAX_BYTES:
            row.update(status="too_large", error=f"> {MAX_BYTES // 1024 // 1024} MB")
        else:
            ext = _sniff(data)
            if ext == "html":
                row.update(status="html", error="nhận được trang HTML thay vì file (file riêng tư hoặc bị chặn)")
            elif ext is None:
                row.update(status="unknown_type", error=f"không nhận dạng được định dạng ({len(data)} byte)")
            else:
                p = RAW / f"{key}{ext}"
                p.write_bytes(data)
                row.update(status="ok", path=str(p.relative_to(ROOT)), bytes=len(data))
    except urllib.error.HTTPError as e:
        row.update(status="http_error", error=f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        row.update(status="error", error=f"{type(e).__name__}: {e}")
    return row


def _unique(manifest):
    seen, out = set(), []
    for m in manifest:
        if m["file_key"] not in seen:
            seen.add(m["file_key"])
            out.append(m)
    return out


def download(manifest, limit=None, delay=1.5, verbose=True):
    """Bước 3: tải hàng loạt. Thư mục Drive chỉ ghi log `skip_folder`, không gọi mạng."""
    ensure_dirs()
    uniq = _unique(manifest)
    folders = [m for m in uniq if not m["download_url"]]
    files = [m for m in uniq if m["download_url"]]
    if limit:
        files = files[:limit]
    log = [{"file_key": m["file_key"], "kind": m["kind"], "status": "skip_folder", "path": "", "bytes": 0,
            "error": "thư mục Drive: không có 1 file cụ thể để tải", "time": _now()} for m in folders]
    for i, m in enumerate(files, 1):
        row = download_one(m)
        net = row.pop("_network")
        if verbose:
            print(f"[{i}/{len(files)}] {m['file_key'][:48]}: {row['status']} {row['error'] if row['error'] != 'cache' else '(cache)'}")
        log.append(row)
        if net:
            time.sleep(delay)
    _upsert_log(DL_LOG, DL_FIELDS, log)
    if MANIFEST.exists():
        sync_manifest_status()
    return log


def read_download_log():
    return _read_csv(DL_LOG)


# ----------------------------------------------------------------------------- bước 2: thử 3 file
def probe_folder(folder_id):
    """Dò xem thư mục Drive có công khai không: đọc trang `embeddedfolderview` và liệt kê file bên trong."""
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}"
    try:
        html = _fetch(url, timeout=30).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return {"status": "http_error", "detail": f"HTTP {e.code}", "entries": []}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"{type(e).__name__}: {e}", "entries": []}
    entries = []
    for m in re.finditer(r'<div class="flip-entry"[^>]*id="entry-([\w-]+)"', html):
        seg = html[m.start(): m.start() + 900]
        href = re.search(r'href="([^"]+)"', seg)
        title = re.search(r'flip-entry-title">([^<]+)<', seg)
        entries.append({"file_id": m.group(1), "name": htmllib.unescape(title.group(1)).strip() if title else "",
                        "is_folder": bool(href and "/folders/" in href.group(1))})
    if entries:
        n_f = sum(e["is_folder"] for e in entries)
        return {"status": "ok", "detail": f"{len(entries)} mục ({len(entries) - n_f} file, {n_f} thư mục con)",
                "entries": entries}
    return {"status": "no_entries", "detail": "không liệt kê được file (thư mục riêng tư hoặc rỗng)", "entries": []}


def probe(manifest, delay=1.5):
    """Bước 2: thử 1 PDF, 1 Sheets, 1 thư mục. Trả về danh sách dòng kết quả."""
    ensure_dirs()
    uniq = _unique(manifest)
    pick = {}
    for m in uniq:
        if m["kind"] in ("drive-file", "google-sheet", "drive-folder") and m["kind"] not in pick:
            pick[m["kind"]] = m
    out = []
    for kind in ("drive-file", "google-sheet", "drive-folder"):
        m = pick.get(kind)
        if not m:
            out.append({"kind": kind, "file_key": "", "status": "no_sample", "detail": "không có file mẫu"})
            continue
        if kind == "drive-folder":
            res = probe_folder(m["file_id"])
            out.append({"kind": kind, "file_key": m["file_key"], "status": res["status"],
                        "detail": res["detail"] + (": " + ", ".join(e["name"] or e["file_id"] for e in res["entries"][:3])
                                                   if res["entries"] else "")})
        else:
            row = download_one(m)
            net = row.pop("_network")
            detail = row["error"] if row["error"] != "cache" else "cache"
            if row["status"] == "ok":
                p = _cached_path(m["file_key"])
                detail = f"{p.suffix}, {row['bytes']} byte"
                if p.suffix == ".pdf":
                    c = classify_pdf(p)
                    detail += f", {c['n_pages']} trang, {c['chars_per_page']} ký tự/trang -> {c['pdf_class']}"
            out.append({"kind": kind, "file_key": m["file_key"], "status": row["status"], "detail": detail})
            _upsert_log(DL_LOG, DL_FIELDS, [row])
            if net:
                time.sleep(delay)
    _write_csv(PROBE_LOG, out, PROBE_FIELDS)
    return out


def expand_folders(manifest, delay=1.5, max_depth=3, verbose=True):
    """Nếu thư mục công khai: thêm các file bên trong (kể cả thư mục con, tối đa max_depth cấp) vào manifest.
    Cột `parent` ghi file_key của thư mục gốc để merge gắn file về đúng bản ghi."""
    new_rows = []
    have = {m["file_key"] for m in manifest}
    for m in _unique(manifest):
        if m["kind"] != "drive-folder" or m["parent"]:
            continue
        queue, visited = [(m["file_id"], 1)], set()
        while queue:
            fid, depth = queue.pop(0)
            if fid in visited:
                continue
            visited.add(fid)
            res = probe_folder(fid)
            time.sleep(delay)
            if verbose:
                print(f"  {m['record_id']} | thư mục {fid[:12]}… (cấp {depth}): {res['status']} {res['detail']}")
            if res["status"] != "ok":
                continue
            for e in res["entries"]:
                if e["is_folder"]:
                    if depth < max_depth:
                        queue.append((e["file_id"], depth + 1))
                    continue
                key = f"drive-file_{e['file_id']}"
                if key in have:
                    continue
                have.add(key)
                kind, fid2, norm, dl = classify_url(f"https://drive.google.com/file/d/{e['file_id']}/view")
                for src in [x for x in manifest if x["file_key"] == m["file_key"]]:
                    new_rows.append({**src, "link_name": e["name"] or src["link_name"], "kind": kind, "file_id": fid2,
                                     "file_key": key, "parent": m["file_key"], "url": norm, "url_norm": norm,
                                     "download_url": dl, "status": "pending"})
    return new_rows


# ----------------------------------------------------------------------------- bước 4: phân loại PDF
def _page_text(page):
    return page.extract_text() or ""


def classify_pdf(path):
    """pdf_text nếu có lớp chữ; scan nếu ít chữ trên mỗi trang (ảnh chụp)."""
    if pdfplumber is None:
        raise RuntimeError("Thiếu pdfplumber: pip install pdfplumber")
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        chars = sum(len(_page_text(p).strip()) for p in pdf.pages)
    cpp = round(chars / n) if n else 0
    return {"n_pages": n, "n_chars": chars, "chars_per_page": cpp,
            "pdf_class": "pdf_text" if cpp >= MIN_CHARS_PER_PAGE else "scan"}


def classify_all(verbose=True):
    rows = []
    for p in sorted(RAW.glob("*.pdf")) if RAW.exists() else []:
        try:
            r = classify_pdf(p)
            r.update(file_key=p.stem, error="")
        except Exception as e:  # noqa: BLE001
            r = {"file_key": p.stem, "n_pages": 0, "n_chars": 0, "chars_per_page": 0, "pdf_class": "error",
                 "error": f"{type(e).__name__}: {e}"}
        if verbose:
            print(f"{p.stem[:48]}: {r['pdf_class']} ({r['n_pages']} trang, {r['chars_per_page']} ký tự/trang) {r['error']}")
        rows.append(r)
    _upsert_log(CLS_LOG, CLS_FIELDS, rows)
    return rows


def read_classify_log():
    return _read_csv(CLS_LOG)


# ----------------------------------------------------------------------------- bước 5: trích xuất
def _ocr_available():
    try:
        import shutil
        import PIL  # noqa: F401
        import pytesseract  # noqa: F401
        return shutil.which("tesseract") is not None
    except ImportError:
        return False


def _ocr_pdf(path):
    """OCR từng trang bằng Tesseract (ngôn ngữ 'vie'). CHƯA kiểm thử với dữ liệu thật."""
    import pytesseract
    out = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            out.append(pytesseract.image_to_string(page.to_image(resolution=200).original, lang="vie").strip())
    return out


def _clean_cell(c):
    return re.sub(r"\s+", " ", c or "").strip()


def _region_text(page, y0, y1):
    """Chữ nằm hoàn toàn trong dải ngang [y0, y1] của trang."""
    if y1 - y0 < 1:
        return ""
    return (page.within_bbox((0, max(0, y0), page.width, min(page.height, y1))).extract_text() or "").strip()


def extract_pdf_text(path):
    """Chữ theo trang, đúng thứ tự đọc. Bảng thật (>= 2 hàng và >= 2 cột) chuyển thành dòng 'ô1 | ô2 | ô3'
    và được chèn đúng vị trí giữa các đoạn chữ. "Bảng" chỉ có 1 cột hoặc 1 hàng (pdfplumber hay nhận nhầm
    đoạn văn có khung/gạch chân) được coi là chữ thường."""
    pages, tables = [], []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            real = []
            for t in page.find_tables():
                rows = [[_clean_cell(c) for c in row] for row in t.extract()]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    real.append((t.bbox, rows))
            if not real:
                pages.append((page.extract_text() or "").strip())
                continue
            parts, y = [], 0.0
            for bbox, rows in sorted(real, key=lambda x: x[0][1]):
                parts.append(_region_text(page, y, bbox[1]))
                parts.append("\n".join(" | ".join(r).rstrip(" |") for r in rows))
                tables.append({"page": i, "rows": rows})
                y = max(y, bbox[3])
            parts.append(_region_text(page, y, page.height))
            pages.append("\n".join(p for p in parts if p))
    return {"text": "\n\n".join(p for p in pages if p), "n_pages": len(pages), "tables": tables}


def extract_pdf(path, pdf_class, ocr=False):
    if pdf_class == "scan":
        if ocr and _ocr_available():
            pages = _ocr_pdf(path)
            return {"status": "ok", "method": "pdf_ocr", "text": "\n\n".join(p for p in pages if p),
                    "n_pages": len(pages), "tables": [], "note": ""}
        return {"status": "needs_ocr", "method": "pdf_ocr", "text": "", "n_pages": 0, "tables": [],
                "note": "PDF dạng ảnh scan; cần OCR (cài Tesseract + gói 'vie' rồi chạy với --ocr)"}
    res = extract_pdf_text(path)
    res.update(status="ok", method="pdf_text", note="")
    return res


def _cell_str(v):
    """Giá trị ô -> chữ. 1.0 -> '1' (Excel lưu số nguyên dạng thực); ngày giờ -> dd/mm/yyyy [HH:MM]."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime.datetime):
        return v.strftime("%d/%m/%Y") if (v.hour, v.minute, v.second) == (0, 0, 0) else v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, datetime.date):
        return v.strftime("%d/%m/%Y")
    return str(v).strip()


def extract_xlsx(path):
    """Mỗi sheet thành các dòng 'ô1 | ô2 | ô3'."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        lines = []
        for row in ws.iter_rows(values_only=True):
            cells = [_cell_str(v) for v in row]
            if any(cells):
                lines.append(" | ".join(cells).rstrip(" |"))
        if lines:
            parts.append(f"## Sheet: {ws.title}\n" + "\n".join(lines))
    return {"status": "ok", "method": "xlsx", "text": "\n\n".join(parts), "n_pages": len(wb.worksheets),
            "tables": [], "note": ""}


def extract_all(ocr=False, force=False, verbose=True):
    """Trích xuất mọi file trong raw_files/. Bỏ qua file đã trích ok (trừ khi force=True)."""
    ensure_dirs()
    done = {r["file_key"]: r for r in _read_csv(EX_LOG)}
    cls = {r["file_key"]: r for r in read_classify_log()}
    rows = []
    files = sorted(p for p in RAW.iterdir() if p.is_file())
    for i, p in enumerate(files, 1):
        key, ext = p.stem, p.suffix.lower()
        if key in done and not force and done[key]["status"] == "ok":
            if verbose:
                print(f"[{i}/{len(files)}] {key[:48]}: đã trích, bỏ qua")
            continue
        try:
            if ext == ".pdf":
                pc = cls.get(key, {}).get("pdf_class") or classify_pdf(p)["pdf_class"]
                res = extract_pdf(p, pc, ocr)
            elif ext == ".xlsx":
                res = extract_xlsx(p)
            else:
                res = {"status": "unsupported", "method": ext.lstrip("."), "text": "", "n_pages": 0, "tables": [],
                       "note": f"chưa hỗ trợ định dạng {ext}"}
        except Exception as e:  # noqa: BLE001
            res = {"status": "error", "method": ext.lstrip("."), "text": "", "n_pages": 0, "tables": [],
                   "note": f"{type(e).__name__}: {e}"}
        text = res["text"].strip()
        if res["status"] == "ok" and not text:
            res["status"], res["note"] = "empty", "không trích được chữ nào"
        if res["status"] == "ok":
            (TEXT / f"{key}.txt").write_text(text, encoding="utf-8")
        if res["tables"]:
            (TEXT / f"{key}.tables.json").write_text(json.dumps(res["tables"], ensure_ascii=False), encoding="utf-8")
        n = res["n_pages"]
        rows.append({"file_key": key, "ext": ext.lstrip("."), "status": res["status"], "method": res["method"],
                     "n_pages": n, "n_chars": len(text), "chars_per_page": round(len(text) / n) if n else 0,
                     "n_tables": len(res["tables"]), "note": res["note"]})
        if verbose:
            print(f"[{i}/{len(files)}] {key[:48]}: {res['status']} {res['method']} ({len(text)} ký tự, {len(res['tables'])} bảng) {res['note']}")
    _upsert_log(EX_LOG, EX_FIELDS, rows)
    return rows


def read_extract_log():
    return _read_csv(EX_LOG)


# ----------------------------------------------------------------------------- bước 6: gắn lại bản ghi
def merge(records=None, manifest=None):
    """Thêm `attachments`, `extracted_text`, `extract_method`, `extract_status`, `n_pages` vào từng bản ghi."""
    records = records if records is not None else load_records()
    manifest = manifest if manifest is not None else load_manifest()
    dl = {r["file_key"]: r for r in read_download_log()}
    ex = {r["file_key"]: r for r in read_extract_log()}
    by_rec = {}
    for m in manifest:
        by_rec.setdefault(m["record_id"], []).append(m)

    merged, stat = [], {}
    for r in records:
        atts, texts, methods, pages = [], [], [], 0
        for m in by_rec.get(r["id"], []):
            if m["kind"] == "drive-folder" and any(x.get("parent") == m["file_key"] for x in manifest):
                continue                     # thư mục đã được thay bằng các file bên trong
            d, e = dl.get(m["file_key"], {}), ex.get(m["file_key"], {})
            atts.append({
                "name": htmllib.unescape(m["link_name"]), "kind": m["kind"], "file_key": m["file_key"], "url": m["url_norm"] or m["url"],
                "download_status": d.get("status", "chưa tải"), "extract_status": e.get("status", "chưa trích"),
                "method": e.get("method", ""), "n_pages": int(e.get("n_pages") or 0), "n_chars": int(e.get("n_chars") or 0),
            })
            tp = TEXT / f"{m['file_key']}.txt"
            if e.get("status") == "ok" and tp.exists():
                texts.append(f"[{htmllib.unescape(m['link_name'])}]\n{tp.read_text(encoding='utf-8')}")
                methods.append(e.get("method", ""))
                pages += int(e.get("n_pages") or 0)
        n_ok = sum(1 for a in atts if a["extract_status"] == "ok")
        if not atts:
            status = "no_attachment"
        elif n_ok == len(atts):
            status = "ok"
        elif n_ok:
            status = "partial"
        elif all(a["download_status"] != "ok" for a in atts):
            status = "not_downloaded"
        else:
            status = "failed"
        stat[status] = stat.get(status, 0) + 1
        r2 = dict(r)
        r2.update(attachments=atts, extracted_text="\n\n".join(texts),
                  extract_method=", ".join(sorted(set(methods))), extract_status=status, n_pages=pages)
        merged.append(r2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged, stat


# ----------------------------------------------------------------------------- bước 7: kiểm tra chất lượng
def quality_report(n_samples=10, preview=500):
    """Thống kê tỷ lệ thành công + chọn ~10 file để đọc bằng mắt (ưu tiên OCR và file có bảng)."""
    merged = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    dl, ex = read_download_log(), read_extract_log()
    by_key = {r["file_key"]: r for r in ex}
    rec_of = {}
    for r in merged:
        for a in r["attachments"]:
            rec_of.setdefault(a["file_key"], r)

    def cnt(rows, key):
        out = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return out

    dl_stat, ex_stat = cnt(dl, "status"), cnt(ex, "status")
    rec_stat = cnt(merged, "extract_status")
    n_dl_ok = dl_stat.get("ok", 0)
    n_ex_ok = ex_stat.get("ok", 0)

    def prio(r):   # OCR trước, rồi nhiều bảng, rồi file dài
        return (r["method"] != "pdf_ocr", -int(r["n_tables"] or 0), -int(r["n_chars"] or 0))
    cands = sorted([r for r in ex if r["status"] == "ok"], key=prio)[:n_samples]

    lines = ["# Báo cáo chất lượng trích xuất", "",
             "## Thống kê", "",
             f"- Tải: {dl_stat}",
             f"- Trích xuất: {ex_stat}",
             f"- Bản ghi theo `extract_status`: {rec_stat}",
             f"- Tỷ lệ tải thành công: {n_dl_ok}/{sum(dl_stat.values()) - dl_stat.get('skip_folder', 0)} file có link tải",
             f"- Tỷ lệ trích được chữ: {n_ex_ok}/{n_dl_ok} file đã tải", "",
             f"## {len(cands)} file để đọc bằng mắt (ưu tiên OCR, rồi file có bảng)", ""]
    for r in cands:
        rec = rec_of.get(r["file_key"], {})
        txt = (TEXT / f"{r['file_key']}.txt").read_text(encoding="utf-8")
        lines += [f"### {r['file_key']}", "",
                  f"- Bản ghi: `{rec.get('id', '?')}` | {rec.get('title', '')[:90]}",
                  f"- Phương pháp: {r['method']} | {r['n_pages']} trang | {r['n_chars']} ký tự | {r['n_tables']} bảng", "",
                  "```", txt[:preview], "```", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return {"download": dl_stat, "extract": ex_stat, "records": rec_stat,
            "samples": [{"file_key": r["file_key"], "record_id": rec_of.get(r["file_key"], {}).get("id", ""),
                         "method": r["method"], "n_pages": r["n_pages"], "n_chars": r["n_chars"],
                         "n_tables": r["n_tables"]} for r in cands]}


# ----------------------------------------------------------------------------- dòng lệnh
def _count(rows, key):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


def main():
    ap = argparse.ArgumentParser(description="Trích xuất chữ từ file đính kèm của crawl_v2")
    ap.add_argument("step", choices=["list", "probe", "expand", "download", "classify", "extract", "merge", "report", "all"])
    ap.add_argument("--limit", type=int, default=None, help="chỉ tải tối đa N file")
    ap.add_argument("--delay", type=float, default=1.5, help="giây nghỉ giữa hai lần tải (mặc định 1.5)")
    ap.add_argument("--ocr", action="store_true", help="OCR PDF dạng ảnh (cần Tesseract + pytesseract)")
    ap.add_argument("--force", action="store_true", help="trích xuất lại cả file đã trích")
    a = ap.parse_args()

    if a.step in ("list", "all"):
        m = build_manifest(load_records())
        save_manifest(m)
        print(f"Danh sách: {len(m)} dòng, {len({x['file_key'] for x in m})} file duy nhất -> {MANIFEST}")
        print("Theo dạng:", _count(m, "kind"))
    if a.step == "probe":
        for r in probe(load_manifest(), a.delay):
            print(f"[{r['kind']}] {r['status']} | {r['file_key'][:50]} | {r['detail']}")
    if a.step == "expand":
        m = load_manifest()
        new = expand_folders(m, a.delay)
        if new:
            save_manifest(m + new)
        print(f"Đã thêm {len(new)} file từ thư mục Drive vào manifest")
    if a.step in ("download", "all"):
        log = download(load_manifest(), limit=a.limit, delay=a.delay)
        print("Kết quả tải:", _count(log, "status"))
    if a.step in ("classify", "all"):
        rows = classify_all()
        print("Phân loại PDF:", _count(rows, "pdf_class") if rows else "không có PDF")
    if a.step in ("extract", "all"):
        rows = extract_all(ocr=a.ocr, force=a.force)
        print("Kết quả trích xuất:", _count(rows, "status") if rows else "không có file mới")
    if a.step in ("merge", "all"):
        _, stat = merge()
        print("Bản ghi theo trạng thái trích xuất:", stat, "->", OUT)
    if a.step in ("report", "all"):
        rep = quality_report()
        print("Báo cáo:", REPORT)
        print("Tải:", rep["download"], "| Trích xuất:", rep["extract"], "| Bản ghi:", rep["records"])


if __name__ == "__main__":
    main()

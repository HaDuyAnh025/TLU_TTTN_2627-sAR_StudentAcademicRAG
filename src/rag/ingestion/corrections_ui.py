"""Giao diện duyệt chỉnh sửa của LLM: Văn bản gốc (ảnh) | LLM sửa | Đúng/Sai | Sửa sai  + nút Accept.

  python scripts/ingest.py --stage corrections-ui     # dựng giao diện và mở máy chủ cục bộ http://127.0.0.1:8765

Máy chủ chỉ nghe ở 127.0.0.1 (không mở ra ngoài). Bấm Accept thì quyết định được ghi thẳng vào lớp hiệu chỉnh
(data/interim/corrected), KHÔNG sửa data/interim/extract. Mặc định mỗi dòng là "Đúng" (chấp nhận bản LLM sửa);
chọn "Sai" thì bắt buộc gõ cách đọc đúng vào ô "Sửa sai". Tiến độ tự lưu, đóng trang mở lại vẫn còn.
"""
from __future__ import annotations

import functools
import json
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from rag.config import EVAL_DIR, ROOT, load_config
from rag.evaluation.extract_eval import load_docs
from rag.evaluation.llm_review import render_page
from rag.ingestion.corrections import CORR_DIR, _load, _refresh, _write

UI_DIR = EVAL_DIR / "corrections_ui"
PENDING = ("applied", "unapplicable", "pending_human")


# ------------------------------------------------------------------ dựng dữ liệu giao diện
def crop_with_context(img, box, min_w: int = 760, min_h: int = 260, min_out_w: int = 640):
    """Cắt vùng quanh chỗ bị sửa kèm NGỮ CẢNH (các ô/dòng lân cận) và vẽ khung đỏ đúng chỗ đó.

    Khung của chữ OCR thường rất nhỏ (một ô bảng); nếu chỉ cắt sát khung, chữ LLM đọc ra có thể nằm ngoài ảnh.
    """
    from PIL import ImageDraw, Image
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    mx = max(160, int(w * 0.8))
    my = max(80, int(h * 2.0))
    left, top, right, bottom = x0 - mx, y0 - my, x1 + mx, y1 + my
    if right - left < min_w:  # đảm bảo vùng đủ rộng/cao, mở đều hai phía
        pad = (min_w - (right - left)) // 2 + 1
        left, right = left - pad, right + pad
    if bottom - top < min_h:
        pad = (min_h - (bottom - top)) // 2 + 1
        top, bottom = top - pad, bottom + pad
    left, top = max(0, left), max(0, top)
    right, bottom = min(img.width, right), min(img.height, bottom)
    crop = img.crop((left, top, right, bottom)).convert("RGB")
    ImageDraw.Draw(crop).rectangle((x0 - left - 3, y0 - top - 3, x1 - left + 3, y1 - top + 3), outline=(220, 38, 38), width=3)
    if crop.width < min_out_w:  # phóng to ảnh nhỏ cho dễ đọc
        k = min_out_w / crop.width
        crop = crop.resize((min_out_w, int(crop.height * k)), Image.LANCZOS)
    return crop


def _risk(it: dict) -> tuple:
    """Chỗ rủi ro cao hiển thị trước: có cảnh báo, quan trọng, LLM chưa chắc."""
    return (0 if it.get("canh_bao") else 1, 0 if it.get("quan_trong") else 1, 0 if it.get("do_chac") != "cao" else 1)


def context_for(base: str, snippet: str, width: int = 140, max_occ: int = 3) -> dict:
    """Ngữ cảnh quanh đoạn OCR bị sửa trong văn bản OCR của trang: phần trước, đoạn đó, phần sau, số dòng.
    Đoạn xuất hiện nhiều lần → liệt kê tối đa max_occ vị trí. Không khớp nguyên văn → tìm gần đúng (bỏ '|', gộp khoảng trắng)."""
    spans, mode, n = [], "chinh_xac", 0
    if snippet:
        n = base.count(snippet)
        start = 0
        while len(spans) < max_occ:
            i = base.find(snippet, start)
            if i < 0:
                break
            spans.append((i, i + len(snippet)))
            start = i + max(1, len(snippet))
        if not spans:
            from rag.evaluation.llm_review import _squash_map
            nb, idx = _squash_map(base)
            sq = _squash_map(snippet)[0].strip()
            pos = nb.find(sq) if sq else -1
            if pos >= 0:
                spans.append((idx[pos], idx[pos + len(sq) - 1] + 1))
                mode, n = "gan_dung", 1
            elif len(snippet.strip()) >= 6:  # vẫn không thấy: tìm đoạn giống nhất (chỉ nhận khi độ giống đủ cao)
                from rapidfuzz import fuzz
                al = fuzz.partial_ratio_alignment(snippet, base, score_cutoff=82)
                if al is not None:
                    spans.append((al.dest_start, al.dest_end))
                    mode, n = "gan_dung", 1
    total = base.count(chr(10)) + 1
    items = []
    for a, b in spans:
        items.append({"truoc": base[max(0, a - width):a], "giua": base[a:b], "sau": base[b:b + width],
                      "cat_dau": a - width > 0, "cat_cuoi": b + width < len(base),
                      "dong": base.count(chr(10), 0, a) + 1, "tong_dong": total})
    return {"so_lan": n, "mode": mode, "items": items}


PART_DIR = ROOT / "data" / "interim"


def part_map(n: int, layer: dict | None = None) -> dict[str, int]:
    """Chia việc theo FILE (mỗi file thuộc đúng một người, nên không ai thấy nội dung file của người khác).
    Gán cân bằng theo số chỗ LLM đã sửa trong file; bảng gán được lưu lại để mọi máy dùng cùng một cách chia."""
    f = PART_DIR / f"phan_viec_{n}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    cnt: dict[str, int] = {}
    for rec in (layer if layer is not None else _load(CORR_DIR)).values():
        cnt[rec["file"]] = cnt.get(rec["file"], 0) + len(rec["items"])
    load, out = [0] * n, {}
    for name, c in sorted(cnt.items(), key=lambda x: (-x[1], x[0])):  # file nặng trước, vào phần đang nhẹ nhất
        k = load.index(min(load))
        out[name] = k
        load[k] += c
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def in_part(rec: dict, part: tuple[int, int] | None, pm: dict | None = None) -> bool:
    return part is None or (pm if pm is not None else part_map(part[1])).get(rec["file"]) == part[0]


def _todo(corr_dir: Path, part: tuple[int, int] | None = None) -> list[tuple[dict, dict]]:
    pm = part_map(part[1]) if part else None
    todo = [(rec, it) for rec in _load(corr_dir).values() if in_part(rec, part, pm) for it in rec["items"]
            if it["status"] in PENDING and not it.get("human_checked")]
    todo.sort(key=lambda x: _risk(x[1]))
    return todo


def _names(rec: dict, it: dict) -> tuple[str, str]:
    safe = it["item_id"].replace("#", "_k")
    return f"images/{safe}.jpg", f"images/{rec['id']}_full.jpg"


def build_rows(cfg: dict | None = None, corr_dir: Path | None = None, out_dir: Path | None = None,
               part: tuple[int, int] | None = None) -> list[dict]:
    """Dựng danh sách dòng (NHANH, không dựng ảnh). Ảnh được ImageMaker tạo khi cần / ở nền."""
    cfg = cfg or load_config("ocr")
    corr_dir, out_dir = corr_dir or CORR_DIR, out_dir or UI_DIR
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    todo = _todo(corr_dir, part)
    base_text = {(d["file"], p["page"]): p["derived"]["text"] for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    rows = []
    for rec, it in todo:
        crop, full = _names(rec, it)
        rows.append({"ctx": context_for(base_text.get((rec["file"], rec["page"]), ""), it["ocr"]),
                     "item_id": it["item_id"], "trang_id": rec["id"], "file": rec["file"], "trang": rec["page"],
                     "loai": it.get("loai", ""), "quan_trong": bool(it.get("quan_trong")), "do_chac": it.get("do_chac", ""),
                     "canh_bao": it.get("canh_bao", []), "status": it["status"], "ocr": it["ocr"], "llm_sua": it["anh_llm"],
                     "anh": crop, "anh_ca_trang": full, "hien_thi": "vung" if it.get("vi_tri") else "ca_trang"})
    (out_dir / "rows.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (out_dir / "index.html").write_text(HTML, encoding="utf-8")
    return rows


class ImageMaker:
    """Tạo ảnh cắt + ảnh cả trang theo TỪNG TRANG (dựng ảnh trang đúng một lần cho mọi chỗ trên trang đó).
    Chạy nền theo thứ tự rủi ro; nếu trình duyệt xin ảnh nào chưa có thì tạo ngay trang chứa ảnh đó."""

    def __init__(self, cfg: dict, corr_dir: Path, out_dir: Path, part: tuple[int, int] | None = None):
        self.dpi = cfg.get("render_dpi", 200)
        self.out = out_dir
        self.lock = threading.Lock()
        self.index = {(d["file"], p["page"]): (d, p) for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
        self.pages: dict[str, tuple[dict, list[dict]]] = {}
        self.by_image: dict[str, str] = {}
        self.order: list[str] = []
        todo = _todo(corr_dir, part)
        for rec, it in todo:
            if rec["id"] not in self.pages:
                self.pages[rec["id"]] = (rec, [])
                self.order.append(rec["id"])
            self.pages[rec["id"]][1].append(it)
            crop, full = _names(rec, it)
            self.by_image[crop] = rec["id"]
            self.by_image[full] = rec["id"]
        self.done = {pid for pid, (rec, its) in self.pages.items()
                     if (self.out / _names(rec, its[0])[1]).exists() and all((self.out / _names(rec, i)[0]).exists() for i in its)}

    def gen_page(self, pid: str) -> None:
        with self.lock:
            if pid in self.done:
                return
            rec, items = self.pages[pid]
            got = self.index.get((rec["file"], rec["page"]))
            if not got:
                self.done.add(pid)
                return
            img = render_page(got[0], got[1], self.dpi)
            for it in items:
                crop_name, full_name = _names(rec, it)
                vt = it.get("vi_tri")
                if vt:
                    crop = crop_with_context(img, vt["box"])
                else:
                    crop = img.copy()
                    crop.thumbnail((1300, 1700))  # không xác định được vị trí → ảnh cả trang, đủ lớn để đọc
                crop.convert("RGB").save(self.out / crop_name, quality=85)
            full = self.out / _names(rec, items[0])[1]
            if not full.exists():
                big = img.copy()
                big.thumbnail((1400, 1900))
                big.convert("RGB").save(full, quality=80)
            self.done.add(pid)

    def ensure(self, rel_path: str) -> None:
        pid = self.by_image.get(rel_path)
        if pid:
            self.gen_page(pid)

    def run_background(self) -> None:
        for pid in self.order:
            try:
                self.gen_page(pid)
            except Exception as e:  # noqa: BLE001 - một trang lỗi không làm dừng cả nền
                print(f"  ! không tạo được ảnh cho {pid}: {type(e).__name__}: {e}")
                self.done.add(pid)


# ------------------------------------------------------------------ Accept
def accept(cfg: dict, corr_dir: Path, decisions: dict) -> tuple[int, dict]:
    """Áp quyết định của người vào lớp hiệu chỉnh. Trả (mã HTTP, kết quả). Không sửa data/interim/extract."""
    errors = []
    for iid, dec in decisions.items():
        if dec.get("quyet_dinh") not in ("dung", "sai"):
            errors.append(f"{iid}: thiếu quyết định")
    if errors:
        return 400, {"ok": False, "loi": errors[:20], "so_loi": len(errors)}
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    layer = _load(corr_dir)
    where = {it["item_id"]: (rec, it) for rec in layer.values() for it in rec["items"]}
    st = {"tong": 0, "dung": 0, "sai": 0, "bo": 0, "dung_nhung_khong_ap_duoc_tu_dong": 0, "khong_tim_thay": 0}
    touched = set()
    now = datetime.now().isoformat(timespec="seconds")
    for iid, dec in decisions.items():
        if iid not in where:
            st["khong_tim_thay"] += 1
            continue
        rec, it = where[iid]
        st["tong"] += 1
        touched.add(rec["id"])
        if dec["quyet_dinh"] == "dung":
            st["dung"] += 1
            it["human_checked"], it["at_nguoi"] = True, now
            base = index[(rec["file"], rec["page"])]["derived"]["text"]
            if it["status"] == "pending_human" and base.count(it["ocr"]) == 1 and it["anh_llm"] != it["ocr"]:
                # chương trình chỉ để chờ người; người đã bấm Đúng và đoạn gốc khớp đúng 1 lần → áp đúng đề xuất của LLM
                it.update(status="human_applied", sua_thanh=it["anh_llm"], nguon="nguoi", llm_da_de_xuat=it["anh_llm"])
            elif it["status"] != "applied":  # LLM đọc đúng nhưng không thay vào văn bản tự động được
                it["status"] = "unapplicable"
                st["dung_nhung_khong_ap_duoc_tu_dong"] += 1
        else:
            # Sai: thay đoạn OCR bằng chữ người gõ. Để trống = "Bỏ": đoạn đó RỖNG (xóa đoạn OCR khỏi văn bản).
            sua = (dec.get("sua_sai") or "").strip()
            st["bo" if not sua else "sai"] += 1
            it.update(status="human_applied", sua_thanh=sua, nguon="nguoi" if sua else "nguoi_bo_rong",
                      human_checked=True, at_nguoi=now, llm_da_de_xuat=it["anh_llm"])
    for pid in touched:
        rec = layer[pid]
        _refresh(rec, index[(rec["file"], rec["page"])]["derived"]["text"])
        _write(corr_dir, rec)
    return 200, {"ok": True, **st, "trang_cap_nhat": len(touched)}


# ------------------------------------------------------------------ máy chủ cục bộ
def make_handler(cfg: dict, corr_dir: Path, ui_dir: Path, maker: "ImageMaker | None" = None):
    state_file = ui_dir / "state.json"
    lock = threading.Lock()

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ui_dir), **kw)

        def log_message(self, *a):  # giữ cửa sổ lệnh gọn
            pass

        def end_headers(self):  # trang và dữ liệu dòng luôn lấy bản mới, tránh trình duyệt giữ bản cũ
            p = self.path.split("?")[0]
            if p.endswith((".html", ".json")) or p in ("/", ""):
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code: int, obj) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = unquote(self.path.split("?")[0])
            if path == "/api/state":
                with lock:
                    self._json(200, json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {})
            else:
                if maker and path.startswith("/images/"):
                    maker.ensure(path.lstrip("/"))  # ảnh chưa có thì tạo ngay (cả trang chứa nó)
                super().do_GET()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"ok": False, "loi": ["JSON không hợp lệ"]})
            with lock:
                if self.path == "/api/save":
                    state_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    return self._json(200, {"ok": True})
                if self.path == "/api/accept":
                    code, res = accept(cfg, corr_dir, payload.get("decisions", {}))
                    if code == 200 and state_file.exists():  # bỏ các dòng đã Accept khỏi tiến độ đã lưu; phần còn lại giữ nguyên
                        try:
                            st = json.loads(state_file.read_text(encoding="utf-8"))
                            for k in ("decisions", "seen"):
                                for iid in payload.get("decisions", {}):
                                    (st.get(k) or {}).pop(iid, None)
                            state_file.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
                        except (json.JSONDecodeError, OSError):
                            pass
                    return self._json(code, res)
            self._json(404, {"ok": False})

    return H


def serve(cfg: dict | None = None, port: int = 8765, open_browser: bool = True, corr_dir: Path | None = None,
          ui_dir: Path | None = None, part: tuple[int, int] | None = None) -> None:
    cfg = cfg or load_config("ocr")
    corr_dir = corr_dir or CORR_DIR
    ui_dir = ui_dir or (UI_DIR if part is None else UI_DIR / f"phan_{part[0] + 1}_{part[1]}")  # mỗi phần có tiến độ riêng
    rows = build_rows(cfg, corr_dir, ui_dir, part)
    if part:
        print(f"Bạn làm PHẦN {part[0] + 1}/{part[1]} (chia theo file; mỗi file thuộc đúng một người).")
    sf = ui_dir / "state.json"
    if sf.exists():  # giữ tiến độ đã lưu (bản cũ có accepted_at thì bỏ)
        try:
            if "accepted_at" in json.loads(sf.read_text(encoding="utf-8")):
                sf.unlink()
        except json.JSONDecodeError:
            sf.unlink()
    print(f"{len(rows)} chỗ LLM đã sửa đang chờ bạn duyệt.")
    if not rows:
        print("Không có gì cần duyệt (chạy llm-review và corrections-build trước).")
        return
    maker = ImageMaker(cfg, corr_dir, ui_dir, part)
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(cfg, corr_dir, ui_dir, maker))
            break
        except OSError:
            continue
    else:
        raise SystemExit("Không mở được cổng nào từ " + str(port))
    threading.Thread(target=maker.run_background, daemon=True).start()
    url = f"http://127.0.0.1:{p}/index.html"
    print(f"Mở giao diện: {url}   (Ctrl+C để dừng)")
    print(f"Ảnh được tạo nền theo từng trang ({len(maker.order)} trang); ảnh nào bạn cần trước sẽ được tạo ngay.")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng.")


HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Duyệt chỉnh sửa của LLM</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--mute:#667085;--line:#d9dde3;--acc:#2457d6;--ok:#12794b;--bad:#b42318;--warn:#a15c07}
@media (prefers-color-scheme:dark){:root{--bg:#10141b;--card:#181e28;--ink:#e6e9ef;--mute:#98a2b3;--line:#2b3442;--acc:#7aa2ff;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.pill{background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mute)}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:8px 18px;cursor:pointer;font:inherit}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc);padding:6px 12px}
button.mini{padding:2px 8px;font-size:12px}
#accept{background:var(--ok);font-weight:600;margin-left:auto}
main{max-width:1280px;margin:0 auto;padding:12px 16px 80px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{background:var(--card);text-align:left;font-size:13px;color:var(--mute);padding:8px 10px;border-bottom:1px solid var(--line)}
td{vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}
tr.sai td{background:rgba(180,35,24,.07)}
tr.seen td.c3{background:rgba(18,121,75,.10)}
.seenlb{margin-top:8px;padding-top:6px;border-top:1px solid var(--line);color:var(--ok);font-weight:600}
td.c1{width:32%}td.c2{width:32%}td.c3{width:10%}td.c4{width:26%}
.pair{display:grid;gap:6px}
.box{border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:var(--bg)}
.box>b{display:block;font-size:12px;color:var(--mute);margin-bottom:2px}
.box.l{border-color:var(--acc)}
.del{background:rgba(180,35,24,.22);border-radius:3px;text-decoration:line-through}
.ins{background:rgba(18,121,75,.25);border-radius:3px;font-weight:600}
.nopos{font-size:12px;color:var(--warn);margin-top:4px}
tr.ctxrow td{padding:2px 10px 12px;border-bottom:2px solid var(--line)}
.ctx{border:1px dashed var(--line);border-radius:8px;padding:6px 10px;background:var(--bg)}
.ctx>.cap{font-size:12px;color:var(--mute);margin-bottom:4px}
.ctxit+.ctxit{margin-top:8px;padding-top:6px;border-top:1px solid var(--line)}
.ctxl{font:13px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.ctxl small{font:11px system-ui;color:var(--mute);display:inline-block;min-width:92px}
mark.hit{background:rgba(220,38,38,.28);color:inherit;border-radius:3px;padding:0 2px;font-weight:600}
mark.fix{background:rgba(18,121,75,.30);color:inherit;border-radius:3px;padding:0 2px;font-weight:600}
@media (max-width:1000px){table,thead,tbody,tr,td{display:block;width:auto!important}thead{display:none}tr{border-bottom:2px solid var(--line);padding:6px 0}td{border:0;padding:6px 10px}}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}
.sub{font-size:12px;color:var(--mute);margin-top:4px;word-break:break-word}
.llm{font:14px/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.tag{display:inline-block;border-radius:6px;padding:0 7px;font-size:12px;border:1px solid var(--line);margin:0 4px 4px 0;color:var(--mute)}
.tag.w{color:var(--warn);border-color:var(--warn)}.tag.i{color:var(--bad);border-color:var(--bad)}
.opt{display:block;margin:2px 0;cursor:pointer}
textarea{width:100%;box-sizing:border-box;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit;min-height:56px}
textarea:disabled{opacity:.45}
.hint{color:var(--mute);font-size:13px;margin:6px 0 10px}
#msg{padding:10px 14px;border-radius:8px;margin:8px 0;display:none;white-space:pre-wrap}
#msg.ok{display:block;background:rgba(18,121,75,.12);border:1px solid var(--ok)}
#msg.err{display:block;background:rgba(180,35,24,.1);border:1px solid var(--bad)}
</style></head><body>
<header><b>Duyệt chỉnh sửa của LLM</b><span class="pill" id="cnt"></span>
<button class="sec" id="fw">Chỉ hiện có cảnh báo</button><button class="sec" id="fs">Chỉ hiện dòng "Sai"</button>
<button class="sec" id="fu">Ẩn dòng đã duyệt</button><button class="sec" id="allseen">Đánh dấu đã duyệt các dòng đang hiện</button>
<button id="accept">Accept các dòng đã duyệt</button></header>
<main>
<p class="hint">Mỗi dòng: <b>ảnh gốc</b> (khung đỏ là chỗ bị sửa) | <b>"OCR đọc"</b> và <b>"LLM sửa thành"</b> cạnh nhau (từ khác nhau được tô màu: đỏ gạch ngang = bị bỏ, xanh = thêm vào) | chọn <b>Đúng</b> (mặc định) hoặc <b>Sai</b> | nếu Sai thì gõ chữ đúng thay cho đoạn "OCR đọc" vào <b>Sửa sai</b> (nút "Giữ nguyên chữ OCR đọc" nếu OCR vốn đúng). Dòng có cảnh báo (số liệu chưa được công cụ OCR thứ hai xác nhận, LLM chưa chắc) được xếp lên đầu. <b>Accept từng phần:</b> tick ô <b>"Đã duyệt"</b> ở cột Đúng/Sai (tự tick khi bạn đổi Đúng/Sai hoặc gõ sửa; hoặc dùng nút "Đánh dấu đã duyệt các dòng đang hiện" sau khi lọc). Bấm <b>Accept</b> chỉ ghi các dòng đã duyệt; dòng chưa duyệt giữ nguyên, lần sau mở lại vẫn còn. Quyết định chỉ ghi vào lớp hiệu chỉnh riêng, không sửa kết quả OCR gốc.</p>
<div id="msg"></div>
<table><thead><tr><th>Văn bản gốc (ảnh)</th><th>LLM sửa</th><th>Đúng / Sai</th><th>Sửa sai</th></tr></thead><tbody id="tb"></tbody></table>
</main>
<script>
let ROWS=[],ST={},SEEN={},onlyW=false,onlyS=false,hideSeen=false;
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function charDiff(x,y){let s=0;while(s<x.length&&s<y.length&&x[x.length-1-s]===y[y.length-1-s])s++;
 let p=0;while(p<x.length-s&&p<y.length-s&&x[p]===y[p])p++;
 const f=(t)=>esc(t.slice(0,p))+(t.length-p-s>0?'@@'+esc(t.slice(p,t.length-s))+'##':"")+esc(t.slice(t.length-s));
 return [f(x).replace("@@",'<span class="del">').replace("##","</span>"),f(y).replace("@@",'<span class="ins">').replace("##","</span>")]}
function diffWords(a,b){const A=String(a||"").split(" "),B=String(b||"").split(" "),n=A.length,m=B.length;
 if(n===1&&m===1&&A[0]!==B[0])return charDiff(A[0],B[0]);
 const L=Array.from({length:n+1},()=>new Array(m+1).fill(0));
 for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)L[i][j]=A[i]===B[j]?L[i+1][j+1]+1:Math.max(L[i+1][j],L[i][j+1]);
 let i=0,j=0;const ha=[],hb=[];
 while(i<n&&j<m){if(A[i]===B[j]){ha.push(esc(A[i]));hb.push(esc(B[j]));i++;j++}
  else if(L[i+1][j]>=L[i][j+1]){ha.push('<span class="del">'+esc(A[i])+'</span>');i++}
  else{hb.push('<span class="ins">'+esc(B[j])+'</span>');j++}}
 while(i<n){ha.push('<span class="del">'+esc(A[i])+'</span>');i++}
 while(j<m){hb.push('<span class="ins">'+esc(B[j])+'</span>');j++}
 return [ha.join(" "),hb.join(" ")]}
function ctxHtml(r){const c=r.ctx;
 if(!c||!c.items||!c.items.length)return '<div class="ctx"><div class="cap">Ngữ cảnh</div><div class="nopos">Không tìm thấy đoạn này trong văn bản OCR của trang (LLM có thể trích không nguyên văn). Hãy dựa vào ảnh.</div></div>';
 let cap="Ngữ cảnh trong văn bản OCR của trang";
 if(c.so_lan>1)cap+=' · đoạn này xuất hiện <b>'+c.so_lan+' lần</b> trong trang (hiện '+c.items.length+' vị trí đầu): chọn đúng chỗ theo ảnh';
 else if(c.mode==="gan_dung")cap+=" · khớp gần đúng (LLM trích không hoàn toàn nguyên văn)";
 return '<div class="ctx"><div class="cap">'+cap+'</div>'+c.items.map((it,k)=>{
  const pre=(it.cat_dau?"… ":"")+esc(it.truoc),post=esc(it.sau)+(it.cat_cuoi?" …":"");
  return '<div class="ctxit"><div class="cap">'+(c.items.length>1?'<b>Vị trí '+(k+1)+'</b> · ':'')+'dòng '+it.dong+'/'+it.tong_dong+' của trang</div>'
   +'<div class="ctxl"><small>OCR hiện tại:</small>'+pre+'<mark class="hit">'+esc(it.giua)+'</mark>'+post+'</div>'
   +'<div class="ctxl"><small>Sau khi LLM sửa:</small>'+pre+'<mark class="fix">'+esc(r.llm_sua)+'</mark>'+post+'</div></div>'}).join("")+'</div>'}
function dec(r){return ST[r.item_id]||{quyet_dinh:"dung",sua_sai:""}}
function saveSoon(){clearTimeout(window._t);window._t=setTimeout(()=>fetch("/api/save",{method:"POST",body:JSON.stringify({decisions:ST,seen:SEEN})}),400)}
const WARN={llm_chua_chac:"LLM chưa chắc",sua_cau_truc_bang_dong:"sửa cấu trúc bảng/dòng, xem kỹ",so_lieu_chua_duoc_ocr_thu_hai_xac_nhan:"số liệu chưa được OCR thứ hai xác nhận"};
function cnt(){const n=ROWS.length,s=ROWS.filter(r=>dec(r).quyet_dinh==="sai").length,v=ROWS.filter(r=>SEEN[r.item_id]).length;
 document.getElementById("cnt").textContent=n+" dòng · đã duyệt "+v+" · chưa duyệt "+(n-v)+" · "+s+" dòng Sai";
 document.getElementById("accept").textContent="Accept "+v+" dòng đã duyệt"}
function draw(){const tb=document.getElementById("tb");tb.innerHTML="";
 ROWS.forEach((r,i)=>{const d=dec(r);if(onlyW&&!r.canh_bao.length)return;if(onlyS&&d.quyet_dinh!=="sai")return;if(hideSeen&&SEEN[r.item_id])return;
  const tr=document.createElement("tr");tr.className=(d.quyet_dinh==="sai"?"sai ":"")+(SEEN[r.item_id]?"seen":"");
  const tags=(r.quan_trong?'<span class="tag i">quan trọng</span>':"")+'<span class="tag">'+esc(r.loai)+'</span>'+r.canh_bao.map(w=>'<span class="tag w">'+esc(WARN[w]||w)+'</span>').join("")+(r.status==="unapplicable"?'<span class="tag w">không thay tự động được (đoạn gốc không khớp đúng 1 lần)</span>':"");
  const df=diffWords(r.ocr,r.llm_sua);
  const nopos=r.hien_thi==="ca_trang"?'<div class="nopos">Không xác định được vị trí chính xác của chỗ này: ảnh là cả trang (bấm vào ảnh để phóng to), hãy tìm đoạn "OCR đọc" bên cạnh.</div>':"";
  tr.innerHTML=`<td class="c1"><a href="${r.anh_ca_trang}" target="_blank"><img loading="lazy" src="${r.anh}"></a>${nopos}<div class="sub">${esc(r.file)} · trang ${r.trang===null?"(ảnh)":r.trang}</div></td>
  <td class="c2"><div>${tags}</div><div class="pair"><div class="box"><b>OCR đọc (chữ sẽ bị thay)</b><div class="llm">${df[0]}</div></div><div class="box l"><b>LLM sửa thành</b><div class="llm">${df[1]}</div></div></div></td>
  <td class="c3"><label class="opt"><input type="radio" name="q${i}" value="dung" ${d.quyet_dinh==="dung"?"checked":""}> Đúng</label><label class="opt"><input type="radio" name="q${i}" value="sai" ${d.quyet_dinh==="sai"?"checked":""}> Sai</label><label class="opt seenlb"><input type="checkbox" class="sn" ${SEEN[r.item_id]?"checked":""}> Đã duyệt</label></td>
  <td class="c4"><textarea ${d.quyet_dinh==="sai"?"":"disabled"} placeholder="Gõ cách đọc đúng (để trống = Bỏ, xóa đoạn)">${esc(d.sua_sai)}</textarea><button class="sec mini" ${d.quyet_dinh==="sai"?"":"disabled"}>Giữ nguyên chữ OCR đọc</button> <button class="sec mini bo" ${d.quyet_dinh==="sai"?"":"disabled"}>Bỏ (xóa đoạn này)</button>${d.quyet_dinh==="sai"&&!(d.sua_sai||"").trim()?'<div class="nopos">Để trống = Bỏ: đoạn "OCR đọc" sẽ bị xóa (thành rỗng).</div>':""}</td>`;
  const ta=tr.querySelector("textarea"),bt=tr.querySelector("button");
  tr.querySelectorAll("input[type=radio]").forEach(x=>x.addEventListener("change",()=>{const v=x.value;ST[r.item_id]={quyet_dinh:v,sua_sai:v==="sai"?(ta.value||r.llm_sua):""};SEEN[r.item_id]=true;saveSoon();cnt();draw()}));
  ta.addEventListener("input",()=>{ST[r.item_id]={quyet_dinh:"sai",sua_sai:ta.value};if(!SEEN[r.item_id]){SEEN[r.item_id]=true;tr.classList.add("seen");tr.querySelector(".sn").checked=true;cnt()}saveSoon()});
  bt.addEventListener("click",()=>{ST[r.item_id]={quyet_dinh:"sai",sua_sai:r.ocr};SEEN[r.item_id]=true;saveSoon();draw()});
  tr.querySelector(".bo").addEventListener("click",()=>{ST[r.item_id]={quyet_dinh:"sai",sua_sai:""};SEEN[r.item_id]=true;saveSoon();draw()});
  tr.querySelector(".sn").addEventListener("change",e=>{if(e.target.checked)SEEN[r.item_id]=true;else delete SEEN[r.item_id];tr.classList.toggle("seen",!!SEEN[r.item_id]);saveSoon();cnt();if(hideSeen)draw()});
  tb.appendChild(tr);
  const cr=document.createElement("tr");cr.className="ctxrow";cr.innerHTML='<td colspan="4">'+ctxHtml(r)+'</td>';tb.appendChild(cr)});cnt()}
function msg(t,c){const m=document.getElementById("msg");m.className=c;m.textContent=t;window.scrollTo(0,0)}
document.getElementById("fw").onclick=()=>{onlyW=!onlyW;draw()};
document.getElementById("fs").onclick=()=>{onlyS=!onlyS;draw()};
document.getElementById("fu").onclick=()=>{hideSeen=!hideSeen;document.getElementById("fu").textContent=hideSeen?"Hiện cả dòng đã duyệt":"Ẩn dòng đã duyệt";draw()};
document.getElementById("allseen").onclick=()=>{
 const vis=ROWS.filter(r=>!(onlyW&&!r.canh_bao.length)&&!(onlyS&&dec(r).quyet_dinh!=="sai")&&!(hideSeen&&SEEN[r.item_id]));
 if(!vis.length)return;
 if(!confirm("Đánh dấu ĐÃ DUYỆT "+vis.length+" dòng đang hiện? (Dòng chưa đổi sẽ tính là Đúng.) Chỉ làm khi bạn đã thật sự xem chúng."))return;
 vis.forEach(r=>{SEEN[r.item_id]=true});saveSoon();draw()};
document.getElementById("accept").onclick=async()=>{
 const rows=ROWS.filter(r=>SEEN[r.item_id]);
 if(!rows.length){msg("Chưa có dòng nào được đánh dấu Đã duyệt.","err");return}
 const out={};rows.forEach(r=>{out[r.item_id]=dec(r)});
 const sd=Object.values(out).filter(d=>d.quyet_dinh==="sai"),b=sd.filter(d=>!(d.sua_sai||"").trim()).length,s=sd.length-b;
 if(!confirm("Accept "+rows.length+" dòng đã duyệt?\\n- "+(rows.length-sd.length)+" dòng Đúng (chấp nhận LLM sửa)\\n- "+s+" dòng Sai (dùng cách bạn đã gõ)\\n- "+b+" dòng Bỏ (Sai và để trống: đoạn đó thành RỖNG, xóa khỏi văn bản)\\n"+(ROWS.length-rows.length)+" dòng chưa duyệt sẽ giữ nguyên."))return;
 const res=await fetch("/api/accept",{method:"POST",body:JSON.stringify({decisions:out})});const j=await res.json();
 if(j.ok){const done=new Set(Object.keys(out));ROWS=ROWS.filter(r=>!done.has(r.item_id));done.forEach(k=>{delete ST[k];delete SEEN[k]});
  msg("Đã Accept "+j.tong+" dòng ("+j.dung+" Đúng, "+j.sai+" Sai, "+j.bo+" Bỏ), cập nhật "+j.trang_cap_nhat+" trang. Còn "+ROWS.length+" dòng chưa duyệt."+(j.dung_nhung_khong_ap_duoc_tu_dong?" Có "+j.dung_nhung_khong_ap_duoc_tu_dong+" dòng Đúng nhưng không thay tự động được vào văn bản (đoạn gốc không khớp đúng 1 lần).":""),"ok");draw()}
 else msg("Không Accept được:\\n"+(j.loi||[]).join("\\n"),"err")};
(async()=>{ROWS=await (await fetch("rows.json")).json();const s=await (await fetch("/api/state")).json();
 if(s.decisions)ST=s.decisions;if(s.seen)SEEN=s.seen;draw()})();
</script></body></html>
"""

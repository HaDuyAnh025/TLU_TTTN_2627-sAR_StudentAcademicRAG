"""Giao diện DUYỆT BẢNG VLM bằng mắt: ảnh trang gốc (zoom/kéo) | bản VLM / VLM thô / OCR cũ, tô màu số-mã khác nhau.

  python scripts/ingest.py --stage table-vlm-review-ui      # mở máy chủ cục bộ http://127.0.0.1:8765 (cổng bận thì tự đổi)

Cùng khuôn với corrections_ui / audit_ui: chỉ thư viện chuẩn Python (http.server), chỉ nghe ở 127.0.0.1, không gọi mạng, không cần
khóa API. Quyết định được ghi vào:
  - configs/table_vlm_fixes.yaml  (mục sửa / force_accept / force_reject; ghi atomic + sao lưu .bak có timestamp trước mỗi lần lưu)
  - data/processed/table_vlm_review_log.jsonl  (kết quả duyệt từng trang: bằng chứng kiểm soát chất lượng)
UI KHÔNG sửa data/interim/table_vlm/ hay data/interim/clean/ và KHÔNG chạy lại chunking: duyệt xong chạy `python scripts/ingest.py --stage chunk`.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from rag.config import ROOT, chunking_config

QUEUES = {"uu_tien": "Ưu tiên", "ocr_recall_thap": "ocr_recall thấp", "spot_check": "Spot check", "ngau_nhien": "Ngẫu nhiên (seed=42)",
          "con_need_review": "Còn need_review"}
SEP_ROW = re.compile(r"\|\s*:?-{3,}:?\s*\|")
KET_QUA = ("dung", "co_sua", "khong_chac", "accept", "reject")
PRIORITY = {"drive-17ALNSt37-HO-NgV3cMygvmVuK0nB0psL": [2, 7, 8, 12, 14, 23, 34, 44, 58],
            "drive-195f57wSWF1hZEwuF6BXtpVeMrw24OYYf": [20, 41]}  # trang 1-based, trùng can_soat/
HINTS = {("drive-17ALNSt37-HO-NgV3cMygvmVuK0nB0psL", 2): ["kiểm tra GE12 → GE112? (GE121 có tiên quyết GE112; sơ cấp 1 là GE111)"],
         ("drive-17ALNSt37-HO-NgV3cMygvmVuK0nB0psL", 7): ["BA14 mã đúng là gì? (các mã cùng nhóm có 3 chữ số)"],
         ("drive-17ALNSt37-HO-NgV3cMygvmVuK0nB0psL", 8): ["kiểm tra 'GE111>4,0' có phải '≥4,0' như các trang khác?"]}
FIXES_HEADER = """# Sửa tay trang table_vlm/ sau khi người soát xác nhận (file này do giao diện table-vlm-review-ui ghi; vẫn sửa tay được).
# Loader áp dụng SAU khi đọc table_vlm/, CHỈ các mục có trang_thai: da_xac_nhan (de_xuat = chưa dùng). `find` phải khớp ĐÚNG 1 lần
# trong văn bản trang (sau khi chuẩn hóa dòng/gắn header), không thì loader báo lỗi.
#   fixes:        sửa chuỗi trong trang VLM
#   force_accept: dùng lại trang need_review
#   force_reject: loại trang VLM đang dùng (quay về OCR cũ)
"""
NUM_RE = re.compile(r"\d+(?:[.,/:\-]\d+)*")
CODE_RE = re.compile(r"(?<![\w])[A-ZĐ]{2,5}\s?\d{2,4}(?![\w])")


def pid_of(doc_id: str, page1: int) -> str:
    return f"{doc_id}|{page1}"


def split_pid(pid: str) -> tuple[str, int]:
    d, p = pid.rsplit("|", 1)
    return d, int(p)


def md_spot_pages(path: Path) -> list[tuple[str, int]]:
    """Các trang trong table_vlm_spot_check.md (theo thứ tự xuất hiện): dòng '### <doc_id> — trang N'."""
    if not path.exists():
        return []
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"^### (\S+) — trang (\d+)\s*$", path.read_text(encoding="utf-8"), re.M)]


def md_random_pages(path: Path) -> list[tuple[str, int]]:
    """Các trang trong mục '## B. ngẫu nhiên' của table_vlm_spot_check.md (10 trang chọn ngẫu nhiên, seed=42, từ các trang spot_check=false)."""
    if not path.exists():
        return []
    txt = path.read_text(encoding="utf-8")
    i = txt.find("## B.")
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"^### (\S+) — trang (\d+)\s*$", txt[i:] if i >= 0 else "", re.M)]


class Store:
    """Dữ liệu + thao tác của giao diện. Chỉ ĐỌC table_vlm/ và clean/; chỉ GHI fixes yaml, log, state và ảnh trong ui_dir."""

    def __init__(self, vlm_dir: Path, clean_dir: Path, fixes_path: Path, log_path: Path, ui_dir: Path, files_dir: Path | None = None,
                 spot_md: Path | None = None, soat_md: Path | None = None, min_match: float = 0.8, summary_path: Path | None = None):
        self.vlm_dir, self.clean_dir, self.fixes_path, self.log_path = vlm_dir, clean_dir, fixes_path, log_path
        self.ui_dir, self.files_dir, self.spot_md, self.soat_md = ui_dir, files_dir, spot_md, soat_md
        self.summary_path = summary_path or ui_dir / "table_vlm_review_summary.md"
        self.min_match = min_match
        self.lock = threading.RLock()
        self.vlm: dict[str, dict] = {}
        self.clean: dict[str, dict[int, dict]] = {}
        self.files: dict[str, str] = {}
        for f in sorted(vlm_dir.glob("*.json")):
            self.vlm[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(clean_dir.glob("*.json")):
            if f.name == "_manifest.json":
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            did = Path(d["file"]).stem
            if did in self.vlm:
                self.clean[did] = {p["page"]: p for p in d["pages"]}
                self.files[did] = d["file"]
        ui_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ đọc
    def page(self, pid: str) -> dict | None:
        did, p1 = split_pid(pid)
        return next((p for p in self.vlm.get(did, {}).get("pages", []) if p["page"] == p1 - 1), None)

    def all_pids(self) -> list[str]:
        return [pid_of(d, p["page"] + 1) for d, rec in self.vlm.items() for p in rec["pages"]]

    def reviews(self) -> dict[str, dict]:
        """Kết quả duyệt MỚI NHẤT của từng trang (dòng cuối của log)."""
        out: dict[str, dict] = {}
        if self.log_path.exists():
            for l in self.log_path.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l)
                    out[r["page_id"]] = r
        return out

    def queue_pids(self) -> dict[str, list[str]]:
        have = set(self.all_pids())
        pri = [pid_of(d, p) for d, ps in PRIORITY.items() for p in ps]
        spot = [pid_of(d, p) for d, p in md_spot_pages(self.spot_md)] if self.spot_md else []
        low, nr = [], []
        for pid in self.all_pids():
            pg = self.page(pid)
            if pg["need_review"]:
                nr.append(pid)
            elif pg["check"].get("ocr_recall", pg["check"].get("recall_vs_ocr", 1)) < 0.7:
                low.append(pid)
        rnd = [pid_of(d, p) for d, p in md_random_pages(self.spot_md)] if self.spot_md else []
        return {"uu_tien": [p for p in pri if p in have], "ocr_recall_thap": low, "spot_check": [p for p in spot if p in have],
                "ngau_nhien": [p for p in rnd if p in have], "con_need_review": nr}

    def queues(self) -> dict:
        rv = self.reviews()
        out = {}
        for name, pids in self.queue_pids().items():
            out[name] = {"label": QUEUES[name], "pages": [
                {"id": p, "doc": split_pid(p)[0][:16], "page": split_pid(p)[1], "ket_qua": (rv.get(p) or {}).get("ket_qua"),
                 "need_review": self.page(p)["need_review"]} for p in pids]}
        return out

    @staticmethod
    def _tokens(text: str) -> set[str]:
        from rag.ingestion.table_vlm import tokens_of
        return tokens_of(text)

    def detail(self, pid: str) -> dict:
        did, p1 = split_pid(pid)
        pg = self.page(pid)
        if pg is None:
            raise KeyError(pid)
        ocr = (self.clean.get(did, {}).get(pg["page"]) or {}).get("text", "")
        tv, to = self._tokens(pg["text"]), self._tokens(ocr)
        raw, norm = pg["text_vlm_raw"].split("\n"), pg["text"].split("\n")
        diff = []
        for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, raw, norm, autojunk=False).get_opcodes():
            if tag != "equal":
                diff.append({"tag": tag, "raw": raw[a0:a1], "norm": norm[b0:b1]})
        c = pg["check"]
        fx = self._fixes_data()
        mine = [{"index": i, **f} for i, f in enumerate(fx.get("fixes") or []) if f["doc_id"] == did and f["page_1based"] == p1]
        forces = {k: [f for f in (fx.get(k) or []) if f["doc_id"] == did and f["page_1based"] == p1] for k in ("force_accept", "force_reject")}
        hints = list(HINTS.get((did, p1), []))
        short = [t for t in sorted(tv - to) if re.fullmatch(r"[A-Z]{2,4}\d{2}", t)]
        if short and len([t for t in tv if re.fullmatch(r"[A-Z]{2,4}\d{3}", t)]) >= 5:
            hints.append("mã chỉ có 2 chữ số (có thể thiếu 1 chữ số): " + ", ".join(short))
        if pg.get("rows_fixed"):
            hints.append(f"đã tự thêm '|' cho {pg['rows_fixed']} dòng bảng (xem tab VLM thô)")
        rv = self.reviews().get(pid)
        return {"id": pid, "doc_id": did, "page_1based": p1, "file": self.files.get(did, ""), "text": pg["text"], "raw": pg["text_vlm_raw"],
                "ocr": ocr, "only_vlm": sorted(tv - to), "only_ocr": sorted(to - tv), "diff": diff, "hints": hints,
                "soat_anh": self._soat_notes(did, p1), "fixes": mine, "force": forces, "review": rv,
                "info": {"match_rate": c["match_rate"], "ocr_recall": c.get("ocr_recall", c.get("recall_vs_ocr")), "need_review": pg["need_review"],
                         "spot_check": c.get("spot_check", False), "continued_header": pg.get("continued_header", False),
                         "rows_fixed": pg.get("rows_fixed", 0), "continued_from_page": pg.get("continued_from_page"), "table_issue": c.get("table_issue", ""), "n_tables": c.get("n_tables"),
                         "model": pg.get("model"), "generated_at": pg.get("generated_at")},
                "image": f"images/{did}_p{p1}.png"}

    def _soat_notes(self, did: str, p1: int) -> list[str]:
        """Nhận xét trong soat_anh.md (nếu có) liên quan đến trang: các dòng nhắc 'trang N' dưới tiêu đề/đoạn có doc_id (hoặc 16 ký tự đầu)."""
        if not self.soat_md or not self.soat_md.exists():
            return []
        out, cur_doc = [], False
        rx = re.compile(rf"(trang|tr\.|p)\s*{p1}\b", re.I)
        for l in self.soat_md.read_text(encoding="utf-8").splitlines():
            if did in l or did[:16] in l:
                cur_doc = True
            if cur_doc and rx.search(l):
                out.append(l.strip())
            elif rx.search(l) and (did in l or did[:16] in l):
                out.append(l.strip())
        return list(dict.fromkeys(out))

    # ------------------------------------------------------------------ fixes yaml
    def _fixes_data(self) -> dict:
        if self.fixes_path.exists():
            return yaml.safe_load(self.fixes_path.read_text(encoding="utf-8")) or {}
        return {}

    def _save_fixes(self, data: dict) -> None:
        """Ghi atomic (file tạm rồi rename) sau khi sao lưu bản cũ thành .bak có timestamp."""
        if self.fixes_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            (self.fixes_path.parent / f"{self.fixes_path.name}.{stamp}.bak").write_bytes(self.fixes_path.read_bytes())
        data.setdefault("fixes", [])
        data.setdefault("force_accept", [])
        data.setdefault("force_reject", [])
        tmp = self.fixes_path.with_name(self.fixes_path.name + ".tmp")
        tmp.write_text(FIXES_HEADER + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
        os.replace(tmp, self.fixes_path)

    def text_after_confirmed(self, pid: str) -> str:
        """Văn bản trang sau khi áp các mục da_xac_nhan hiện có (đúng thứ tự loader)."""
        did, p1 = split_pid(pid)
        text = self.page(pid)["text"]
        for f in self._fixes_data().get("fixes") or []:
            if f["doc_id"] == did and f["page_1based"] == p1 and f.get("trang_thai") == "da_xac_nhan" and text.count(f["find"]) == 1:
                text = text.replace(f["find"], f["replace"])
        return text

    def header_warning(self, pid: str, replace: str) -> str:
        """Trang đã continued_header=true mà `replace` có dòng phân cách |---|: nguy cơ gắn header 2 lần (sinh dòng '---' trong bảng)."""
        pg = self.page(pid)
        if pg and pg.get("continued_header") and SEP_ROW.search(replace or ""):
            return f"Trang này đã được gắn header tự động từ trang {pg.get('continued_from_page')}: mục sửa có dòng phân cách |---| sẽ làm header bị gắn 2 lần."
        return ""

    def check_fix(self, pid: str, find: str, replace: str) -> dict:
        """find phải khớp ĐÚNG 1 lần trong văn bản trang (sau các mục đã xác nhận). Trả cả dòng trước/sau khi sửa."""
        if not find:
            return {"ok": False, "so_lan": 0, "loi": "find trống"}
        text = self.text_after_confirmed(pid)
        n = text.count(find)
        if n != 1:
            return {"ok": False, "so_lan": n, "loi": f"find khớp {n} lần (cần đúng 1)"}
        i = text.index(find)
        a, b = text.rfind("\n", 0, i) + 1, text.find("\n", i + len(find))
        b = len(text) if b < 0 else b
        before = text[a:b]
        after = before.replace(find, replace, 1)
        return {"ok": True, "so_lan": 1, "truoc": before, "sau": after, "canh_bao_header": self.header_warning(pid, replace)}

    def add_fix(self, pid: str, find: str, replace: str, ly_do: str, nguoi: str, ghi_chu: str = "", ack_header: bool = False) -> dict:
        with self.lock:
            chk = self.check_fix(pid, find, replace)
            if not chk["ok"]:
                return chk
            if chk["canh_bao_header"] and not ack_header:  # phải bấm xác nhận lần nữa mới lưu
                return {"ok": False, "can_xac_nhan": True, "canh_bao": chk["canh_bao_header"], "loi": chk["canh_bao_header"]}
            did, p1 = split_pid(pid)
            data = self._fixes_data()
            data.setdefault("fixes", []).append({"doc_id": did, "page_1based": p1, "find": find, "replace": replace, "ly_do": ly_do,
                                                 "trang_thai": "da_xac_nhan", "nguoi_soat": nguoi, "thoi_gian": _now(), "ghi_chu": ghi_chu})
            self._save_fixes(data)
            self.log(pid, "co_sua", nguoi, ghi_chu, {"muc_sua": {"find": find, "replace": replace}})
            return {**chk, "ok": True}

    def confirm_fix(self, pid: str, index: int, nguoi: str, ghi_chu: str = "", ack_header: bool = False) -> dict:
        with self.lock:
            did, p1 = split_pid(pid)
            data = self._fixes_data()
            fx = data.get("fixes") or []
            if not (0 <= index < len(fx)) or fx[index]["doc_id"] != did or fx[index]["page_1based"] != p1:
                return {"ok": False, "loi": "không tìm thấy mục sửa"}
            if fx[index].get("trang_thai") != "de_xuat":  # chỉ mục đang chờ duyệt mới xác nhận được (tu_choi / thay_the / da_xac_nhan thì không)
                return {"ok": False, "loi": f"mục sửa đang ở trạng thái {fx[index].get('trang_thai')}, không phải de_xuat"}
            chk = self.check_fix(pid, fx[index]["find"], fx[index]["replace"])
            if not chk["ok"]:
                return chk
            if chk["canh_bao_header"] and not ack_header:
                return {"ok": False, "can_xac_nhan": True, "canh_bao": chk["canh_bao_header"], "loi": chk["canh_bao_header"]}
            fx[index].update(trang_thai="da_xac_nhan", nguoi_soat=nguoi, thoi_gian=_now(), ghi_chu=ghi_chu or fx[index].get("ghi_chu", ""))
            self._save_fixes(data)
            self.log(pid, "co_sua", nguoi, ghi_chu, {"muc_sua": {"find": fx[index]["find"], "replace": fx[index]["replace"]}})
            return {"ok": True}

    def set_force(self, pid: str, kind: str, nguoi: str, ghi_chu: str = "") -> dict:
        """kind = accept (dùng lại trang need_review) | reject (loại trang đang dùng)."""
        if kind not in ("accept", "reject"):
            return {"ok": False, "loi": "kind phải là accept hoặc reject"}
        with self.lock:
            did, p1 = split_pid(pid)
            key = f"force_{kind}"
            data = self._fixes_data()
            lst = data.setdefault(key, [])
            ent = next((f for f in lst if f["doc_id"] == did and f["page_1based"] == p1), None)
            if ent is None:
                ent = {"doc_id": did, "page_1based": p1}
                lst.append(ent)
            ent.update(ly_do=ghi_chu or ent.get("ly_do", ""), trang_thai="da_xac_nhan", nguoi_soat=nguoi, thoi_gian=_now(), ghi_chu=ghi_chu)
            other = data.get("force_reject" if kind == "accept" else "force_accept") or []
            other[:] = [f for f in other if not (f["doc_id"] == did and f["page_1based"] == p1)]  # accept và reject loại trừ nhau
            self._save_fixes(data)
            self.log(pid, kind, nguoi, ghi_chu)
            return {"ok": True}

    # ------------------------------------------------------------------ log
    def log(self, pid: str, ket_qua: str, nguoi: str, ghi_chu: str = "", extra: dict | None = None) -> dict:
        if ket_qua not in KET_QUA:
            raise ValueError(f"ket_qua không hợp lệ: {ket_qua}")
        did, p1 = split_pid(pid)
        queues = [q for q, ps in self.queue_pids().items() if pid in ps]
        rec = {"thoi_gian": _now(), "nguoi_soat": nguoi, "page_id": pid, "doc_id": did, "page_1based": p1, "hang_doi": queues,
               "ket_qua": ket_qua, "ghi_chu": ghi_chu, **(extra or {})}
        with self.lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    # ------------------------------------------------------------------ tổng kết
    def summary(self) -> dict:
        rv = self.reviews()
        per = {}
        for name, pids in self.queue_pids().items():
            res = {k: 0 for k in KET_QUA}
            done = 0
            for p in pids:
                r = rv.get(p)
                if r:
                    done += 1
                    res[r["ket_qua"]] += 1
            per[name] = {"label": QUEUES[name], "tong": len(pids), "da_duyet": done, **res}
        total = {k: sum(1 for r in rv.values() if r["ket_qua"] == k) for k in KET_QUA}
        fx = self._fixes_data()
        confirmed = {k: [f for f in (fx.get(k) or []) if f.get("trang_thai") == "da_xac_nhan"] for k in ("fixes", "force_accept", "force_reject")}
        other = {st: [f for f in (fx.get("fixes") or []) if f.get("trang_thai") == st] for st in ("de_xuat", "tu_choi", "thay_the")}
        from rag.evaluation.audit_ui import wilson
        r = per["ngau_nhien"]
        lo, hi = wilson(r["dung"], r["da_duyet"])
        est = {"n_chon": r["tong"], "n_da_duyet": r["da_duyet"], "dung": r["dung"], "co_sua": r["co_sua"],
               "ty_le_dung": round(r["dung"] / r["da_duyet"], 3) if r["da_duyet"] else None, "ci95": [round(lo, 3), round(hi, 3)]}
        return {"hang_doi": per, "tong_trang_da_duyet": len(rv), "tong": total, "da_xac_nhan": confirmed, "muc_khac": other, "uoc_luong_ngau_nhien": est}

    def summary_md(self) -> str:
        s = self.summary()
        md = ["# Tổng kết duyệt bảng VLM", "", f"Tạo lúc {_now()}. Trang đã duyệt (tính theo kết quả mới nhất mỗi trang): **{s['tong_trang_da_duyet']}**.", "",
              "| Hàng đợi | Đã duyệt / Tổng | Đúng | Có sửa | Không chắc | Accept | Reject |", "|---|---|---|---|---|---|---|"]
        for q in s["hang_doi"].values():
            md.append(f"| {q['label']} | {q['da_duyet']}/{q['tong']} | {q['dung']} | {q['co_sua']} | {q['khong_chac']} | {q['accept']} | {q['reject']} |")
        t = s["tong"]
        md += ["", f"Tổng (không trùng trang): đúng {t['dung']}, có sửa {t['co_sua']}, không chắc {t['khong_chac']}, accept {t['accept']}, reject {t['reject']}.", ""]
        e = s["uoc_luong_ngau_nhien"]
        md += ["## Ước lượng tỉ lệ đúng của VLM (hàng đợi ngẫu nhiên)", "",
               "Đây là con số DUY NHẤT dùng được để ước lượng độ đúng của VLM: 10 trang chọn ngẫu nhiên (seed=42) trong các trang không bị gắn spot_check. "
               "Các hàng đợi khác chọn trang có vấn đề nên bị thiên lệch.", "",
               "| Số trang chọn | Đã duyệt | Đúng | Có sửa | Tỉ lệ đúng | Khoảng tin cậy 95% (Wilson) |", "|---|---|---|---|---|---|",
               f"| {e['n_chon']} | {e['n_da_duyet']} | {e['dung']} | {e['co_sua']} | {e['ty_le_dung']} | {e['ci95'][0]} – {e['ci95'][1]} |", "",
               "Mẫu nhỏ (n=10) nên khoảng tin cậy rộng.", ""]
        for key, title in (("fixes", "Mục sửa da_xac_nhan"), ("force_accept", "force_accept da_xac_nhan"), ("force_reject", "force_reject da_xac_nhan")):
            items = s["da_xac_nhan"][key]
            md += [f"## {title} ({len(items)})", ""]
            for f in items:
                extra = f": `{f['find']}` → `{f['replace']}`" if key == "fixes" else ""
                md.append(f"- {f['doc_id']} trang {f['page_1based']}{extra} — {f.get('ly_do', '')} ({f.get('nguoi_soat', '')}, {f.get('thoi_gian', '')})")
            md.append("")
        for st, title in (("de_xuat", "Mục sửa de_xuat (chờ duyệt)"), ("tu_choi", "Mục sửa tu_choi (đã từ chối)"), ("thay_the", "Mục sửa thay_the (đã bị mục khác thay)")):
            items = s["muc_khac"][st]
            md += [f"## {title} ({len(items)})", ""]
            for f in items:
                why = f.get("ly_do_tu_choi") or (f"thay bởi {f.get('thay_the_boi')}" if f.get("thay_the_boi") else f.get("ly_do", ""))
                md.append(f"- {f['doc_id']} trang {f['page_1based']} — {why}")
            md.append("")
        md += ["Sau khi duyệt xong chạy lại chunking: `python scripts/ingest.py --stage chunk --config all`", ""]
        return "\n".join(md)

    def export_summary(self) -> Path:
        self.summary_path.write_text(self.summary_md(), encoding="utf-8")
        return self.summary_path

    # ------------------------------------------------------------------ ảnh
    def ensure_image(self, rel: str) -> None:
        """images/<doc_id>_p<N>.png: dựng khi trình duyệt xin lần đầu (dpi 200: bảng rất rộng cần zoom được)."""
        m = re.fullmatch(r"images/(.+)_p(\d+)\.png", rel)
        if not m or self.files_dir is None:
            return
        dest = self.ui_dir / rel
        did, p1 = m.group(1), int(m.group(2))
        if dest.exists() or did not in self.files:
            return
        from rag.ingestion.ocr_engines import render_pdf_page
        with self.lock:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            render_pdf_page(self.files_dir / self.files[did], p1 - 1, 200).save(tmp, format="PNG")
            os.replace(tmp, dest)

    # ------------------------------------------------------------------ nguoi soat (state)
    def user(self) -> str:
        sf = self.ui_dir / "state.json"
        return (json.loads(sf.read_text(encoding="utf-8")).get("nguoi_soat", "") if sf.exists() else "")

    def set_user(self, name: str) -> None:
        (self.ui_dir / "state.json").write_text(json.dumps({"nguoi_soat": name.strip()}, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ máy chủ cục bộ
def make_handler(store: Store):
    ui_dir = store.ui_dir

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ui_dir), **kw)

        def log_message(self, *a):
            pass

        def end_headers(self):
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
            u = urlparse(self.path)
            path = unquote(u.path)
            q = parse_qs(u.query)
            try:
                if path == "/api/queues":
                    return self._json(200, {"queues": store.queues(), "nguoi_soat": store.user()})
                if path == "/api/page":
                    return self._json(200, store.detail(q["id"][0]))
                if path == "/api/summary":
                    return self._json(200, store.summary())
            except KeyError:
                return self._json(404, {"ok": False, "loi": "không có trang này"})
            if path.startswith("/images/"):
                try:
                    store.ensure_image(path.lstrip("/"))
                except Exception as e:  # noqa: BLE001 - báo rõ nguyên nhân thay vì để trình duyệt hiện ảnh vỡ
                    print(f"  ! không dựng được ảnh {path}: {type(e).__name__}: {e}")
                    return self._json(500, {"ok": False, "loi": f"{type(e).__name__}: {e}"})
            super().do_GET()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            try:
                p = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"ok": False, "loi": "JSON không hợp lệ"})
            nguoi = p.get("nguoi_soat") or store.user()
            try:
                if self.path == "/api/user":
                    store.set_user(p.get("nguoi_soat", ""))
                    return self._json(200, {"ok": True})
                if self.path == "/api/review":
                    if not nguoi:
                        return self._json(400, {"ok": False, "loi": "chưa nhập người soát"})
                    store.log(p["page_id"], p["ket_qua"], nguoi, p.get("ghi_chu", ""))
                    return self._json(200, {"ok": True})
                if self.path == "/api/fix/check":
                    return self._json(200, store.check_fix(p["page_id"], p.get("find", ""), p.get("replace", "")))
                if self.path in ("/api/fix/add", "/api/fix/confirm", "/api/force") and not nguoi:
                    return self._json(400, {"ok": False, "loi": "chưa nhập người soát"})
                if self.path == "/api/fix/add":
                    res = store.add_fix(p["page_id"], p.get("find", ""), p.get("replace", ""), p.get("ly_do", ""), nguoi, p.get("ghi_chu", ""),
                                        bool(p.get("ack_header")))
                    return self._json(200 if res["ok"] else (409 if res.get("can_xac_nhan") else 400), res)
                if self.path == "/api/fix/confirm":
                    res = store.confirm_fix(p["page_id"], int(p["index"]), nguoi, p.get("ghi_chu", ""), bool(p.get("ack_header")))
                    return self._json(200 if res["ok"] else (409 if res.get("can_xac_nhan") else 400), res)
                if self.path == "/api/force":
                    res = store.set_force(p["page_id"], p["kind"], nguoi, p.get("ghi_chu", ""))
                    return self._json(200 if res["ok"] else 400, res)
                if self.path == "/api/summary/export":
                    return self._json(200, {"ok": True, "file": str(store.export_summary())})
            except (KeyError, ValueError) as e:
                return self._json(400, {"ok": False, "loi": f"{type(e).__name__}: {e}"})
            self._json(404, {"ok": False})

    return H


def default_store() -> Store:
    cc = chunking_config()
    P = cc["paths"]
    from rag.ingestion.loader import FILES_DIR
    out = P["out_dir"]
    return Store(P["table_vlm_dir"], P["clean_dir"], P["table_vlm_fixes"], out / "table_vlm_review_log.jsonl", out / "table_vlm_review_ui", FILES_DIR,
                 out / "table_vlm_spot_check.md", out / "soat_anh.md", cc["table_vlm"]["min_match_rate"], out / "table_vlm_review_summary.md")


def serve(port: int = 8765, open_browser: bool = True, store: Store | None = None) -> None:
    store = store or default_store()
    (store.ui_dir / "index.html").write_text(HTML, encoding="utf-8")
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(store))
            break
        except OSError:
            continue
    else:
        raise SystemExit("Không mở được cổng nào từ " + str(port))
    url = f"http://127.0.0.1:{p}/index.html"
    n = sum(len(q["pages"]) for q in store.queues().values())
    print(f"{len(store.all_pids())} trang VLM; {n} lượt trong các hàng đợi.")
    print(f"Mở giao diện duyệt bảng VLM: {url}   (Ctrl+C để dừng)")
    print("UI không chạy lại chunking. Duyệt xong chạy: python scripts/ingest.py --stage chunk --config all")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng.")


HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Duyệt bảng VLM</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--mute:#667085;--line:#d9dde3;--acc:#2457d6;--ok:#12794b;--bad:#b42318;--warn:#a15c07}
@media (prefers-color-scheme:dark){:root{--bg:#10141b;--card:#181e28;--ink:#e6e9ef;--mute:#98a2b3;--line:#2b3442;--acc:#7aa2ff;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
header{background:var(--card);border-bottom:1px solid var(--line);padding:8px 14px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.pill{background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mute)}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc);padding:5px 10px}
button.ok{background:var(--ok)}button.bad{background:var(--bad)}button.warn{background:var(--warn)}button.mini{padding:1px 8px;font-size:12px}
input,textarea{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit;width:100%}
#wrap{flex:1;display:flex;min-height:0}
#side{width:230px;border-right:1px solid var(--line);background:var(--card);overflow:auto;padding:8px;flex:none}
.qh{margin:10px 0 2px;font-weight:600;cursor:pointer;display:flex;justify-content:space-between}
.qh.on{color:var(--acc)}
.pg{padding:2px 6px;border-radius:6px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;color:var(--mute)}
.pg.on{background:var(--bg);color:var(--ink);outline:1px solid var(--acc)}
.pg .st{font-size:11px}.st.dung,.st.accept{color:var(--ok)}.st.co_sua{color:var(--acc)}.st.khong_chac{color:var(--warn)}.st.reject{color:var(--bad)}
#main{flex:1;display:flex;min-width:0}
#viewer{flex:1.1;position:relative;overflow:hidden;background:#222;min-width:0}
#viewer img{position:absolute;left:0;top:0;transform-origin:0 0;user-select:none;-webkit-user-drag:none;max-width:none;background:#fff}
#vc{position:absolute;right:8px;top:8px;display:flex;gap:4px;z-index:3}
#right{flex:1.3;overflow:auto;padding:10px 14px;min-width:0}
.info{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.tag{border:1px solid var(--line);border-radius:6px;padding:0 7px;font-size:12px;color:var(--mute)}.tag.w{color:var(--warn);border-color:var(--warn)}.tag.b{color:var(--bad);border-color:var(--bad)}.tag.g{color:var(--ok);border-color:var(--ok)}
.tabs{display:flex;gap:4px;margin:6px 0}.tabs button{background:transparent;color:var(--acc);border:1px solid var(--line)}.tabs button.on{background:var(--acc);color:#fff}
.box{border:1px solid var(--line);border-radius:8px;background:var(--card);padding:8px;margin-bottom:8px;overflow:auto;max-height:46vh}
.box table{border-collapse:collapse;font-size:13px}.box td,.box th{border:1px solid var(--line);padding:2px 6px;vertical-align:top}.box th{background:var(--bg)}
pre{white-space:pre-wrap;word-break:break-word;font:13px/1.45 ui-monospace,Consolas,monospace;margin:0}
mark.y{background:rgba(250,204,21,.55);color:inherit;border-radius:3px}mark.r{background:rgba(220,38,38,.35);color:inherit;border-radius:3px}
.chip{display:inline-block;border-radius:6px;padding:0 6px;margin:1px;font:12px ui-monospace,Consolas,monospace}.chip.y{background:rgba(250,204,21,.5)}.chip.r{background:rgba(220,38,38,.3)}
.hint{color:var(--warn);font-size:13px;margin:2px 0}.cap{font-size:12px;color:var(--mute);margin:6px 0 2px}
.fx{border:1px dashed var(--line);border-radius:8px;padding:6px 8px;margin:4px 0;font-size:13px}
.del{background:rgba(180,35,24,.22);text-decoration:line-through}.ins{background:rgba(18,121,75,.25)}
#msg{padding:6px 10px;border-radius:8px;margin:6px 0;display:none;white-space:pre-wrap}#msg.ok{display:block;background:rgba(18,121,75,.12);border:1px solid var(--ok)}#msg.err{display:block;background:rgba(180,35,24,.1);border:1px solid var(--bad)}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
dialog{border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);max-width:720px;width:90vw}
</style></head><body>
<header><b>Duyệt bảng VLM</b><span class="pill" id="prog"></span>
<label>Người soát <input id="who" style="width:150px" placeholder="tên bạn"></label>
<label><input type="checkbox" id="hide" style="width:auto"> chỉ hiện trang chưa duyệt</label>
<button class="sec" id="prev">← Trước</button><button class="sec" id="next">Sau →</button>
<button class="sec" id="sum" style="margin-left:auto">Tổng kết</button></header>
<div id="wrap"><div id="side"></div>
<div id="main"><div id="viewer"><div id="vc"><button class="sec mini" id="zi">+</button><button class="sec mini" id="zo">−</button><button class="sec mini" id="zf">Vừa khung</button><button class="sec mini" id="z1">100%</button></div><img id="img" alt=""></div>
<div id="right"><div id="msg"></div><div id="detail">Chọn một trang ở thanh bên.</div></div></div></div>
<dialog id="dlg"><div id="dlgc"></div><p><button class="sec" onclick="document.getElementById('dlg').close()">Đóng</button></p></dialog>
<script>
let Q={},curQ=null,idx=0,D=null,tab="vlm",hide=false;
const $=id=>document.getElementById(id);
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
async function api(p,b){const r=await fetch(p,b?{method:"POST",body:JSON.stringify(b)}:{});return r.json()}
function msg(t,c){const m=$("msg");m.className=c;m.textContent=t;if(c==="ok")setTimeout(()=>{if(m.textContent===t)m.className=""},3500)}
/* ---- token (cùng quy tắc tokens_of ở phía Python) ---- */
const NUM=/\d+(?:[.,\/:\-]\d+)*/g,CODE=/(?<![\w])[A-ZĐ]{2,5}\s?\d{2,4}(?![\w])/g;
const nn=s=>s.replace(/^[,.]+|[,.]+$/g,"").replace(/^(\d+),(\d{1,2})$/,"$1.$2");
function hl(text,set,cls){const R=[];for(const m of text.matchAll(CODE)){const t=m[0].replace(/\s/g,"");if(set.has(t))R.push([m.index,m.index+m[0].length])}
 for(const m of text.matchAll(NUM)){const t=nn(m[0]);if(t&&set.has(t))R.push([m.index,m.index+m[0].length])}
 R.sort((a,b)=>a[0]-b[0]||b[1]-a[1]);let o="",p=0;for(const [s,e] of R){if(s<p)continue;o+=esc(text.slice(p,s))+'<mark class="'+cls+'">'+esc(text.slice(s,e))+'</mark>';p=e}return o+esc(text.slice(p))}
function cells(l){let s=l.trim();if(s.startsWith("|"))s=s.slice(1);if(s.endsWith("|"))s=s.slice(0,-1);return s.split("|").map(x=>x.trim())}
function mdHtml(t,set,cls){const L=t.split("\n");let o="",i=0;
 while(i<L.length){if(L[i].trim().startsWith("|")){const B=[];while(i<L.length&&L[i].trim().startsWith("|")){B.push(L[i]);i++}
   const sep=B.length>1&&/^\s*\|?\s*:?-{3,}/.test(B[1]);let h="<table>";
   B.forEach((l,k)=>{if(sep&&k===1)return;const th=sep&&k===0;h+="<tr>"+cells(l).map(c=>"<"+(th?"th":"td")+">"+hl(c,set,cls)+"</"+(th?"th":"td")+">").join("")+"</tr>"});
   o+=h+"</table>"+(sep?"":'<div class="hint">⚠ bảng không có dòng phân cách |---|</div>')}
  else{o+="<div>"+hl(L[i],set,cls)+"</div>";i++}}return o}
/* ---- hàng đợi ---- */
async function loadQ(keep){const r=await api("/api/queues");Q=r.queues;if(!$("who").value)$("who").value=r.nguoi_soat||"";
 if(!curQ||!Q[curQ])curQ=Object.keys(Q)[0];renderSide()}
function vis(){return Q[curQ].pages.map((p,i)=>({...p,i})).filter(p=>!hide||!p.ket_qua)}
function renderSide(){let h="";for(const [k,q] of Object.entries(Q)){const d=q.pages.filter(p=>p.ket_qua).length;
  h+='<div class="qh '+(k===curQ?"on":"")+'" data-q="'+k+'"><span>'+esc(q.label)+'</span><span>'+d+'/'+q.pages.length+'</span></div>';
  if(k===curQ)h+=vis().map(p=>'<div class="pg '+(p.i===idx?"on":"")+'" data-i="'+p.i+'"><span>'+esc(p.doc)+' · tr.'+p.page+(p.need_review?' ⚠':'')+'</span><span class="st '+(p.ket_qua||"")+'">'+(p.ket_qua?"✓ "+p.ket_qua:"")+'</span></div>').join("")}
 $("side").innerHTML=h;$("side").querySelectorAll(".qh").forEach(e=>e.onclick=()=>{curQ=e.dataset.q;idx=0;renderSide();openPage()});
 $("side").querySelectorAll(".pg").forEach(e=>e.onclick=()=>{idx=+e.dataset.i;renderSide();openPage()});
 const q=Q[curQ],d=q.pages.filter(p=>p.ket_qua).length;$("prog").textContent=q.label+": đã duyệt "+d+"/"+q.pages.length}
function go(dlt){const v=vis();if(!v.length)return;let k=v.findIndex(p=>p.i===idx);k=Math.max(0,Math.min(v.length-1,(k<0?0:k)+dlt));idx=v[k].i;renderSide();openPage()}
/* ---- trang ---- */
async function openPage(){const p=Q[curQ].pages[idx];if(!p){$("detail").textContent="Hàng đợi trống.";return}
 D=await api("/api/page?id="+encodeURIComponent(p.id));setImg("/"+D.image);render()}
function render(){const d=D,i=d.info,sv=new Set(d.only_vlm),so=new Set(d.only_ocr);
 const tg=(t,c)=>'<span class="tag '+(c||"")+'">'+t+'</span>';
 let h='<div><b>'+esc(d.doc_id)+'</b> · trang '+d.page_1based+'</div><div class="info">'+tg("khớp số "+i.match_rate,i.match_rate<0.8?"b":"")+tg("ocr_recall "+i.ocr_recall,i.ocr_recall<0.7?"b":"")
  +tg("need_review "+i.need_review,i.need_review?"b":"g")+tg("spot_check "+i.spot_check,i.spot_check?"w":"")+tg("continued_header "+i.continued_header)+tg("rows_fixed "+i.rows_fixed)+(i.table_issue?tg(esc(i.table_issue),"w"):"")
  +(d.review?tg("đã duyệt: "+d.review.ket_qua+" ("+esc(d.review.nguoi_soat)+")","g"):"")+'</div>';
 d.hints.forEach(x=>h+='<div class="hint">💡 '+esc(x)+'</div>');d.soat_anh.forEach(x=>h+='<div class="hint">📝 soat_anh.md: '+esc(x)+'</div>');
 h+='<div class="tabs">'+[["vlm","a) Bản VLM (chuẩn hóa)"],["raw","b) VLM thô + khác biệt"],["ocr","c) OCR cũ"]].map(([k,l])=>'<button data-t="'+k+'" class="'+(tab===k?"on":"")+'">'+l+'</button>').join("")+'</div>';
 if(tab==="vlm")h+='<div class="box">'+mdHtml(d.text,sv,"y")+'</div>';
 if(tab==="raw"){h+='<div class="box"><pre>'+hl(d.raw,sv,"y")+'</pre></div>';
  h+='<div class="cap">Khác biệt thô → chuẩn hóa ('+d.diff.length+' chỗ)</div><div class="box">'+(d.diff.length?d.diff.map(x=>'<div class="fx"><div class="del">'+esc(x.raw.join("\n"))+'</div><div class="ins">'+esc(x.norm.join("\n"))+'</div></div>').join(""):"Không khác biệt.")+'</div>'}
 if(tab==="ocr")h+='<div class="box"><pre>'+hl(d.ocr,so,"r")+'</pre></div>';
 h+='<div class="cap">Số/mã chỉ có ở VLM (vàng) — '+d.only_vlm.length+'</div><div>'+(d.only_vlm.map(x=>'<span class="chip y">'+esc(x)+'</span>').join("")||"—")+'</div>';
 h+='<div class="cap">Số/mã có ở OCR cũ nhưng KHÔNG có ở VLM (đỏ) — '+d.only_ocr.length+'</div><div>'+(d.only_ocr.map(x=>'<span class="chip r">'+esc(x)+'</span>').join("")||"—")+'</div>';
 h+='<div class="cap">Mục sửa của trang này</div>';
 if(!d.fixes.length)h+='<div class="cap">(chưa có)</div>';
 const TT={de_xuat:"đề xuất (chờ duyệt)",da_xac_nhan:"đã xác nhận",tu_choi:"đã từ chối",thay_the:"đã thay thế"};
 d.fixes.forEach(f=>h+='<div class="fx"><b>['+esc(TT[f.trang_thai]||f.trang_thai)+']</b> <code>'+esc(f.find.slice(0,200))+'</code> → <code>'+esc(f.replace.slice(0,200))+'</code><br>'+esc(f.ly_do||"")
   +(f.ly_do_tu_choi?'<br><i>Từ chối: '+esc(f.ly_do_tu_choi)+'</i>':"")+(f.thay_the_boi?'<br><i>Thay bởi mục lúc '+esc(f.thay_the_boi)+'</i>':"")+(f.nguoi_soat?' · '+esc(f.nguoi_soat)+' '+esc(f.thoi_gian||""):"")
   +(f.trang_thai==="de_xuat"?' <button class="ok mini" data-cf="'+f.index+'">Xác nhận mục sửa</button>':"")+'</div>');
 ["force_accept","force_reject"].forEach(k=>d.force[k].forEach(f=>h+='<div class="fx"><b>'+k+' ['+esc(f.trang_thai)+']</b> '+esc(f.ly_do||"")+'</div>'));
 h+='<div class="acts"><button class="ok" id="bOk">Đúng (A)</button><button class="sec" id="bAdd">Thêm sửa…</button>'
  +(i.need_review?'<button class="sec" id="bFa">force_accept</button>':'<button class="sec" id="bFr">force_reject</button>')+'<button class="warn" id="bUn">Không chắc (U)</button></div>'
  +'<div class="cap">Ghi chú</div><textarea id="note" rows="2" placeholder="ghi chú tự do (lưu cùng quyết định)">'+esc(d.review?d.review.ghi_chu||"":"")+'</textarea>';
 $("detail").innerHTML=h;
 $("detail").querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{tab=b.dataset.t;render()});
 $("bOk").onclick=()=>review("dung");$("bUn").onclick=()=>review("khong_chac");$("bAdd").onclick=addDlg;
 if($("bFa"))$("bFa").onclick=()=>force("accept");if($("bFr"))$("bFr").onclick=()=>force("reject");
 $("detail").querySelectorAll("[data-cf]").forEach(b=>b.onclick=()=>confirmFix(+b.dataset.cf))}
function who(){const w=$("who").value.trim();if(!w){msg("Nhập tên người soát ở trên cùng trước.","err");$("who").focus();return null}api("/api/user",{nguoi_soat:w});return w}
const note=()=>($("note")?$("note").value:"");
async function after(r,okmsg,adv){if(r.ok){msg(okmsg,"ok");await loadQ();if(adv)go(1);else openPage()}else msg("Không lưu được: "+(r.loi||""),"err")}
async function review(k){const w=who();if(!w)return;await after(await api("/api/review",{page_id:D.id,ket_qua:k,ghi_chu:note(),nguoi_soat:w}),"Đã ghi: "+k,true)}
async function force(k){const w=who();if(!w)return;if(!confirm("force_"+k+" cho trang này? Ghi vào configs/table_vlm_fixes.yaml (da_xac_nhan)."))return;
 await after(await api("/api/force",{page_id:D.id,kind:k,ghi_chu:note(),nguoi_soat:w}),"Đã ghi force_"+k,true)}
async function confirmFix(ix){const w=who();if(!w)return;const b={page_id:D.id,index:ix,ghi_chu:note(),nguoi_soat:w};let r=await api("/api/fix/confirm",b);
 if(r.can_xac_nhan){if(!confirm("⚠ "+r.canh_bao+"\n\nBấm OK nếu vẫn muốn xác nhận mục sửa này."))return;r=await api("/api/fix/confirm",{...b,ack_header:true})}
 await after(r,"Đã xác nhận mục sửa",false)}
function addDlg(){$("dlgc").innerHTML='<h3>Thêm sửa — trang '+D.page_1based+'</h3><div class="cap">find (phải khớp đúng 1 lần trong text của trang; có thể nhiều dòng)</div><textarea id="ff" rows="3"></textarea><div class="cap">replace (xuống dòng được giữ nguyên: bảng Markdown cần mỗi dòng bảng một dòng)</div><textarea id="fr" rows="6"></textarea><div class="cap">lý do</div><input id="fl">'
  +'<div id="fp" class="box" style="margin-top:8px"></div><p><button class="sec" id="fc">Kiểm tra / xem trước</button> <button class="ok" id="fs">Lưu mục sửa</button></p>';
 $("dlg").showModal();
 const chk=async()=>{const r=await api("/api/fix/check",{page_id:D.id,find:$("ff").value,replace:$("fr").value});
  $("fp").innerHTML=r.ok?(r.canh_bao_header?'<div class="hint">⚠ '+esc(r.canh_bao_header)+' (sẽ phải xác nhận lần nữa khi lưu)</div>':'')+'<div class="cap">Dòng trước:</div><div class="del">'+esc(r.truoc)+'</div><div class="cap">Dòng sau:</div><div class="ins">'+esc(r.sau)+'</div>':'<div class="hint">'+esc(r.loi)+'</div>';return r};
 $("fc").onclick=chk;
 $("fs").onclick=async()=>{const w=who();if(!w)return;const r=await chk();if(!r.ok)return;
  const b={page_id:D.id,find:$("ff").value,replace:$("fr").value,ly_do:$("fl").value,ghi_chu:note(),nguoi_soat:w};let s=await api("/api/fix/add",b);
  if(s.can_xac_nhan){if(!confirm("⚠ "+s.canh_bao+"\n\nBấm OK nếu vẫn muốn lưu mục sửa này."))return;s=await api("/api/fix/add",{...b,ack_header:true})}
  if(s.ok){$("dlg").close();await after(s,"Đã lưu mục sửa (da_xac_nhan)",false)}else $("fp").innerHTML='<div class="hint">'+esc(s.loi||"")+'</div>'}}
/* ---- ảnh: zoom bằng con lăn, kéo bằng chuột ---- */
let Z={s:1,x:0,y:0,w:0,h:0};
function applyZ(){$("img").style.transform="translate("+Z.x+"px,"+Z.y+"px) scale("+Z.s+")"}
function fit(){const v=$("viewer"),im=$("img");Z.w=im.naturalWidth;Z.h=im.naturalHeight;if(!Z.w)return;Z.s=Math.min(v.clientWidth/Z.w,v.clientHeight/Z.h);Z.x=(v.clientWidth-Z.w*Z.s)/2;Z.y=0;applyZ()}
function setImg(src){const im=$("img"),v=$("viewer");let e=$("imgerr");if(e)e.remove();im.style.display="";im.onload=fit;
 im.onerror=()=>{im.style.display="none";const d=document.createElement("div");d.id="imgerr";d.style.cssText="color:#fff;padding:16px";d.innerHTML="Không tải được ảnh trang gốc.<br><small>"+esc(src)+"</small><br><button class='sec' onclick='openPage()'>Thử lại</button>";v.appendChild(d)};
 im.src=src+"?t="+Date.now()}
function zoom(f,cx,cy){const v=$("viewer"),r=v.getBoundingClientRect();cx=cx==null?v.clientWidth/2:cx-r.left;cy=cy==null?v.clientHeight/2:cy-r.top;
 const ns=Math.max(.05,Math.min(8,Z.s*f));Z.x=cx-(cx-Z.x)*ns/Z.s;Z.y=cy-(cy-Z.y)*ns/Z.s;Z.s=ns;applyZ()}
$("viewer").addEventListener("wheel",e=>{e.preventDefault();zoom(e.deltaY<0?1.15:1/1.15,e.clientX,e.clientY)},{passive:false});
let drag=null;$("viewer").addEventListener("mousedown",e=>{drag=[e.clientX,e.clientY,Z.x,Z.y];e.preventDefault()});
window.addEventListener("mousemove",e=>{if(drag){Z.x=drag[2]+e.clientX-drag[0];Z.y=drag[3]+e.clientY-drag[1];applyZ()}});window.addEventListener("mouseup",()=>drag=null);
$("zi").onclick=()=>zoom(1.3);$("zo").onclick=()=>zoom(1/1.3);$("zf").onclick=fit;$("z1").onclick=()=>{Z.s=1;Z.x=0;Z.y=0;applyZ()};
/* ---- phím tắt, điều hướng, tổng kết ---- */
$("prev").onclick=()=>go(-1);$("next").onclick=()=>go(1);$("hide").onchange=e=>{hide=e.target.checked;renderSide()};
document.addEventListener("keydown",e=>{if(["INPUT","TEXTAREA"].includes(e.target.tagName)||$("dlg").open)return;
 if(e.key==="ArrowLeft")go(-1);else if(e.key==="ArrowRight")go(1);else if((e.key==="a"||e.key==="A")&&D)review("dung");else if((e.key==="u"||e.key==="U")&&D)review("khong_chac")});
$("sum").onclick=async()=>{const s=await api("/api/summary");
 let h="<h3>Tổng kết duyệt</h3><table border=1 cellpadding=4 style='border-collapse:collapse'><tr><th>Hàng đợi</th><th>Đã duyệt/Tổng</th><th>Đúng</th><th>Có sửa</th><th>Không chắc</th><th>Accept</th><th>Reject</th></tr>"
  +Object.values(s.hang_doi).map(q=>"<tr><td>"+esc(q.label)+"</td><td>"+q.da_duyet+"/"+q.tong+"</td><td>"+q.dung+"</td><td>"+q.co_sua+"</td><td>"+q.khong_chac+"</td><td>"+q.accept+"</td><td>"+q.reject+"</td></tr>").join("")+"</table>"
  +"<p>Trang đã duyệt (không trùng): <b>"+s.tong_trang_da_duyet+"</b></p><p><b>Ước lượng tỉ lệ đúng của VLM (hàng đợi ngẫu nhiên):</b> "+s.uoc_luong_ngau_nhien.dung+"/"+s.uoc_luong_ngau_nhien.n_da_duyet+" đúng, "+s.uoc_luong_ngau_nhien.co_sua+" có sửa; tỉ lệ đúng "+s.uoc_luong_ngau_nhien.ty_le_dung+" (KTC 95%: "+s.uoc_luong_ngau_nhien.ci95.join(" – ")+")</p><h4>Mục da_xac_nhan</h4>"
  +(["fixes","force_accept","force_reject"].map(k=>"<div class='cap'>"+k+" ("+s.da_xac_nhan[k].length+")</div>"+s.da_xac_nhan[k].map(f=>"<div class='fx'>"+esc(f.doc_id)+" tr."+f.page_1based+(k==="fixes"?": <code>"+esc(f.find)+"</code> → <code>"+esc(f.replace)+"</code>":"")+" — "+esc(f.ly_do||"")+"</div>").join("")).join(""))
  +"<p><button id='exp'>Xuất table_vlm_review_summary.md</button> <span id='expm'></span></p><p class='cap'>UI không chạy lại chunking. Duyệt xong chạy: python scripts/ingest.py --stage chunk --config all</p>";
 $("dlgc").innerHTML=h;$("dlg").showModal();$("exp").onclick=async()=>{const r=await api("/api/summary/export",{});$("expm").textContent=r.ok?"Đã ghi "+r.file:"Lỗi"}};
loadQ().then(()=>{if(Q[curQ]&&Q[curQ].pages.length)openPage()});
</script></body></html>
"""

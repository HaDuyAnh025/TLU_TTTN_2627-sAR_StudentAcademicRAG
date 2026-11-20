"""Bước LÀM SẠCH (clean): chọn văn bản dùng cho chunk/embed từ kết quả trích xuất + các lớp hiệu chỉnh.

  python scripts/ingest.py --stage clean          # dựng data/interim/clean/<tên file>.json (+ _manifest.json)
  python scripts/ingest.py --stage clean-verify   # dựng lại trong bộ nhớ và so với file đã ghi (phát hiện sửa tay)

Nguyên tắc:
  - data/interim/extract (OCR gốc) và các lớp hiệu chỉnh KHÔNG bị sửa. Văn bản sạch là kết quả tính toán xác định từ chúng.
  - Trang có lớp chữ PDF (text_layer): lấy nguyên văn derived.text.
  - Trang OCR: văn bản OCR gốc + CHỈ các chỗ sửa thỏa chính sách bên dưới:
      1) chỗ NGƯỜI ĐÃ DUYỆT (Đúng, hoặc người gõ lại/bỏ) và đang có hiệu lực;
      2) chỗ LLM tự sửa mà CHƯA ai duyệt chỉ được nhận khi là sửa chữ/dấu (`chu_dau`), giữ nguyên mọi chuỗi chữ số và số dấu `|`, và không
         có cảnh báo về số liệu hay cấu trúc bảng. Lý do: ở phần đã duyệt xong, loại này bị người bác chỉ ~7% (bảng, dòng thiếu/thừa,
         số liệu bị bác 19-80%). Chính sách này nằm ở ADOPT_UNREVIEWED, đổi được và chạy lại; khi có bản duyệt thì tự dùng bản duyệt.
  - Chỗ người đã bấm Đúng nhưng chưa thay vào văn bản được (đoạn gốc không khớp/lặp nhiều lần) KHÔNG được dùng; đếm riêng để xử lý sau.
  - Làm sạch ký tự chỉ ở mức an toàn: chuẩn hóa Unicode NFC, bỏ ký tự điều khiển/độ rộng bằng 0, bỏ khoảng trắng cuối dòng.
    Chưa bỏ header/footer và không động đến dấu `|` của bảng.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from rag.config import ROOT, load_config
from rag.evaluation.extract_eval import load_docs
from rag.ingestion.corrections import ACTIVE, CORR_DIR, NUM_RE, _load, apply_items, sha

CLEAN_DIR = ROOT / "data" / "interim" / "clean"
RESCAN_DIR = ROOT / "data" / "interim" / "corrected_rescan"
LAYERS = {"corrected": CORR_DIR, "corrected_rescan": RESCAN_DIR}
SCHEMA = 1
ADOPT_UNREVIEWED = ("chu_dau",)  # loại sửa của LLM được nhận khi chưa ai duyệt
BLOCKING_WARNINGS = {"so_lieu_chua_duoc_ocr_thu_hai_xac_nhan", "sua_cau_truc_bang_dong"}
POLICY = {"nhan_sua_chua_duyet_loai": list(ADOPT_UNREVIEWED), "chu_so_phai_giu_nguyen": True, "so_dau_cot_phai_giu_nguyen": True,
          "canh_bao_chan": sorted(BLOCKING_WARNINGS), "van_ban_sach": "NFC, bo ky tu dieu khien/do rong 0, bo khoang trang cuoi dong"}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    t = "".join(c for c in t if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))
    return "\n".join(line.rstrip() for line in t.split("\n"))


def usable(it: dict) -> tuple[bool, str]:
    """Chỗ sửa này có được đưa vào văn bản sạch không? Trả (được/không, lý do)."""
    if it["status"] not in ACTIVE:
        if it["status"] == "unapplicable" and it.get("human_checked"):
            return False, "nguoi_bam_dung_nhung_chua_ap_duoc"
        return False, "khong_hieu_luc"
    if it.get("human_checked"):
        return True, "nguoi_da_duyet"
    loai = it.get("loai", "")
    if (it["status"] == "applied" and loai in ADOPT_UNREVIEWED and NUM_RE.findall(it["ocr"]) == NUM_RE.findall(it["sua_thanh"])
            and it["ocr"].count("|") == it["sua_thanh"].count("|") and "\n" not in it["sua_thanh"]
            and not (set(it.get("canh_bao", [])) & BLOCKING_WARNINGS)):
        return True, "llm_chu_dau_chua_duyet"
    return False, "llm_chua_duyet_bi_loai:" + (loai or "?")


def load_layers() -> dict[str, tuple[str, dict]]:
    """page id → (tên lớp, bản ghi). Một trang chỉ được nằm trong MỘT lớp."""
    out: dict[str, tuple[str, dict]] = {}
    for name, path in LAYERS.items():
        for pid, rec in _load(path).items():
            if pid in out:
                raise SystemExit(f"Trang {pid} nằm trong cả hai lớp hiệu chỉnh ({out[pid][0]} và {name}); cần xử lý trước khi làm sạch.")
            out[pid] = (name, rec)
    return out


def clean_page(d: dict, p: dict, layers: dict, stats: Counter) -> dict:
    from rag.evaluation.llm_review import page_key
    base = p["derived"]["text"]
    out = {"page": p["page"], "route": p["route"], "flags_goc": p["quality"]["flags"], "base_text_sha256": sha(base)}
    pid = page_key(d, p)
    got = layers.get(pid) if p["route"] == "ocr" else None
    if got and got[1].get("base_text_sha256") != sha(base):
        stats["lop_cu_khong_khop_van_ban_goc"] += 1  # lớp được dựng từ bản OCR khác → không dùng
        got = None
    if p["route"] != "ocr":
        out.update(nguon_van_ban="text_layer", lop=None)
        text = base
        stats["trang_text_layer"] += 1
    elif not got:
        out.update(nguon_van_ban="ocr_goc", lop=None)
        text = base
        stats["trang_ocr_khong_co_lop"] += 1
    else:
        layer, rec = got
        chosen, excl = [], Counter()
        for it in rec["items"]:
            ok, why = usable(it)
            if ok:
                chosen.append(it)
                stats["sua_" + why] += 1
            elif it["status"] != "no_change":
                excl[why] += 1
                stats["loai_" + why.split(":")[0]] += 1
        text, skipped = apply_items(base, chosen)
        stats[f"trang_ocr_lop_{layer}"] += 1
        out.update(nguon_van_ban="ocr_hieu_chinh" if chosen else "ocr_goc", lop=layer, so_sua_dung=len(chosen) - len(skipped),
                   so_sua_khong_ap_duoc=len(skipped), sua_bi_loai=dict(excl))
        if skipped:
            stats["sua_khong_ap_duoc_trong_van_ban"] += len(skipped)
    out["text"] = normalize(text)
    return out


def build(cfg: dict | None = None) -> tuple[dict[str, dict], Counter]:
    cfg = cfg or load_config("ocr")
    layers = load_layers()
    stats: Counter = Counter()
    docs = {}
    for d in load_docs(cfg):
        pages = []
        for p in d["pages"]:
            if p.get("error"):
                stats["trang_loi_bo_qua"] += 1
                continue
            pages.append(clean_page(d, p, layers, stats))
        docs[d["file"]] = {"schema": SCHEMA, "file": d["file"], "extract_input_sha256": d["input_sha256"], "pages": pages}
    stats["file"], stats["trang"] = len(docs), sum(len(v["pages"]) for v in docs.values())
    return docs, stats


def _fname(file: str) -> str:
    return "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in Path(file).stem)[:120] + ".json"


def run(cfg: dict | None = None, out_dir: Path | None = None) -> dict:
    out_dir = out_dir or CLEAN_DIR
    docs, stats = build(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob("*.json")) + list(out_dir.glob("*.sha256")):
        old.unlink()
    names = {}
    for file, doc in docs.items():
        fn = _fname(file)
        assert fn not in names, f"trùng tên {fn}"
        names[fn] = file
        data = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
        (out_dir / fn).write_bytes(data)
        (out_dir / (fn + ".sha256")).write_text(hashlib.sha256(data).hexdigest(), encoding="utf-8")
    manifest = {"schema": SCHEMA, "tao_luc": datetime.now().isoformat(timespec="seconds"), "chinh_sach": POLICY,
                "lop_hieu_chinh": {k: str(v.relative_to(ROOT)) for k, v in LAYERS.items()}, "thong_ke": dict(stats), "file": names}
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(stats)


def verify(cfg: dict | None = None, out_dir: Path | None = None) -> dict:
    """Dựng lại trong bộ nhớ và so với file đã ghi: mã băm niêm phong, nội dung từng trang, thiếu/thừa file."""
    out_dir = out_dir or CLEAN_DIR
    docs, _ = build(cfg)
    problems = []
    for file, doc in docs.items():
        fn = _fname(file)
        f = out_dir / fn
        if not f.exists():
            problems.append(f"thiếu {fn}")
            continue
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != (out_dir / (fn + ".sha256")).read_text(encoding="utf-8").strip():
            problems.append(f"{fn}: mã băm niêm phong không khớp (file bị sửa)")
        if json.loads(data.decode("utf-8")) != doc:
            problems.append(f"{fn}: nội dung khác kết quả dựng lại (lớp hiệu chỉnh hoặc extract đã đổi, hoặc file bị sửa)")
    extra = {p.name for p in out_dir.glob("*.json") if not p.name.startswith("_")} - {_fname(f) for f in docs}
    problems += [f"thừa {x}" for x in sorted(extra)]
    return {"ok": not problems, "so_file": len(docs), "van_de": problems[:30], "so_van_de": len(problems)}

"""Đưa các chỗ NGƯỜI ĐÃ DUYỆT nhưng KHÔNG thay vào văn bản được (đoạn gốc không khớp / lặp / chồng lấn) ra duyệt lại, theo CẢ DÒNG.

  python scripts/ingest.py --stage relabel-build   # tạo mục chờ duyệt (loai `ap_lai`) trong lớp hiệu chỉnh + dựng thư mục tạm chỉ gồm các mục đó
  python scripts/ingest.py --stage relabel-ui      # giao diện duyệt quen thuộc, CHỈ hiện các mục này
  python scripts/ingest.py --stage relabel-merge   # đưa quyết định về đúng lớp hiệu chỉnh (corrected / corrected_rescan)

Mỗi mục mới: "OCR đọc" = cả dòng (hoặc vài dòng) chứa chỗ lỗi, đủ để khớp đúng một lần trong văn bản trang. "LLM sửa thành" = dòng đó
với các chữ sửa bạn từng gõ đã được áp lại ở những chỗ xác định được (nếu không có gợi ý thì bằng đúng chữ OCR, bạn tự gõ).
Thẻ cảnh báo trên mỗi dòng nhắc lại bạn từng gõ gì cho đoạn nào. Mục cũ không bị sửa; vì mục mới bao trọn chúng nên khi bạn duyệt xong
mục mới sẽ được ưu tiên áp. Không sửa data/interim/extract.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from rapidfuzz import fuzz

from rag.config import EVAL_DIR, ROOT, load_config
from rag.evaluation.extract_eval import load_docs
from rag.evaluation.llm_review import _squash_map, locate
from rag.ingestion import cleaner
from rag.ingestion.corrections import NUM_RE, _load, _now, _refresh, _write, apply_items, merge_from

STAGE_DIR = ROOT / "data" / "interim" / "corrected_relabel"
UI_DIR = EVAL_DIR / "relabel_ui"
MIN_FUZZY = 80


def _span(base: str, it: dict) -> tuple[tuple[int, int] | None, str | None]:
    """Vị trí đoạn của mục trong văn bản trang: (khoảng, ghi chú). Không có nguyên văn thì tìm DÒNG giống nhất."""
    key = it.get("ocr_khop") or it["ocr"]
    n = base.count(key)
    if n >= 1:
        k = it.get("lan_thu")
        i = base.find(key)
        for _ in range(k if (n > 1 and k is not None and 0 <= k < n) else 0):
            i = base.find(key, i + len(key))
        return (i, i + len(key)), (f"đoạn «{key[:40]}» lặp {n} lần trong trang, đang lấy lần hiện trong ảnh" if n > 1 and it.get("lan_thu") is None else None)
    sq = _squash_map(key)[0].strip()
    best, pos, off = (0.0, None), 0, 0
    for line in base.split("\n"):
        sl = _squash_map(line)[0]
        if sq and sl:
            sc = fuzz.partial_ratio(sq, sl)
            if sc > best[0]:
                best = (sc, (off, off + len(line)))
        off += len(line) + 1
    if best[0] >= MIN_FUZZY and best[1][1] > best[1][0]:
        return best[1], "đoạn cũ không khớp nguyên văn nào, đang lấy dòng giống nhất (xem kỹ ảnh)"
    return None, None


def _lines(base: str, a: int, b: int) -> tuple[int, int]:
    return base.rfind("\n", 0, a) + 1, (base.find("\n", b) if base.find("\n", b) >= 0 else len(base))


def plan(cfg: dict | None = None) -> list[dict]:
    """Tìm các mục người đã duyệt nhưng không áp được và dựng mục duyệt lại (chưa ghi). Mỗi phần tử: lớp, trang, mục mới."""
    cfg = cfg or load_config("ocr")
    dpi = cfg.get("render_dpi", 200)
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    out = []
    for pid, (layer, rec) in cleaner.load_layers().items():
        pg = index[(rec["file"], rec["page"])]
        base = pg["derived"]["text"]
        chosen = [it for it in rec["items"] if cleaner.usable(it)[0]]
        _, sk = apply_items(base, chosen)
        if not sk or any(it["item_id"].startswith(f"{pid}#r") for it in rec["items"]):
            continue
        sk_items = [it for it in chosen if it["item_id"] in sk]
        spans = []  # (a, b, item, ghi_chu, chính_xác)
        for it in sk_items:
            sp, note = _span(base, it)
            if sp:
                spans.append([sp[0], sp[1], it, note, base.count(it.get("ocr_khop") or it["ocr"]) >= 1])
            else:
                out.append({"layer": layer, "pid": pid, "loi": f"không xác định được vị trí của {it['item_id']}"})
        for it in chosen:  # mục đã áp được nhưng chồng lấn với mục bị bỏ: kéo vào cùng nhóm để không mất sửa đã duyệt
            if it in sk_items or it.get("bo_qua_khi_ap"):
                continue
            sp, _ = _span(base, it)
            if sp and any(sp[0] < s[1] and sp[1] > s[0] for s in spans):
                spans.append([sp[0], sp[1], it, None, True])
        if not spans:
            continue
        iv = sorted([(*_lines(base, s[0], s[1]), s) for s in spans], key=lambda x: x[0])  # mở rộng ra cả dòng rồi gộp các nhóm chạm nhau
        groups = []
        for a, b, s in iv:
            if groups and a <= groups[-1][1]:
                groups[-1][1] = max(groups[-1][1], b)
                groups[-1][2].append(s)
            else:
                groups.append([a, b, [s]])
        for n, (a, b, members) in enumerate(groups):
            lo, hi, tries = a, b, 0
            while base.count(base[lo:hi]) != 1 and tries < 3:  # chưa duy nhất → lấy thêm dòng phía trên
                if lo == 0:
                    break
                lo = base.rfind("\n", 0, lo - 1) + 1
                tries += 1
            if base.count(base[lo:hi]) != 1:
                out.append({"layer": layer, "pid": pid, "loi": f"dòng {base[a:b][:40]!r} không duy nhất ngay cả khi lấy thêm dòng"})
                continue
            exact = sorted([m for m in members if m[4]], key=lambda m: -(m[1] - m[0]))  # chỉ mục có nguyên văn mới áp lại được
            taken, rep = [], []
            for m in exact:
                if all(m[1] <= t[0] or m[0] >= t[1] for t in taken):
                    taken.append((m[0], m[1]))
                    rep.append((m[0], m[1], m[2]["sua_thanh"]))
            text = base[lo:hi]
            for x, y, r in sorted(rep, reverse=True):
                text = text[: x - lo] + r + text[y - lo:]
            hints = []
            for m in members:
                it = m[2]
                hints.append(f"Bạn từng gõ «{it['sua_thanh'][:90]}» thay cho «{(it.get('ocr_khop') or it['ocr'])[:90]}»" if it["sua_thanh"]
                             else f"Bạn từng chọn BỎ đoạn «{it['ocr'][:90]}»")
                if m[3]:
                    hints.append(m[3])
            if text == base[lo:hi]:
                hints.append("Chưa có gợi ý: hãy xem ảnh và gõ cả dòng đúng")
            out.append({"layer": layer, "pid": pid, "rec": rec, "base": base, "pg": pg, "dpi": dpi,
                        "item": {"item_id": f"{pid}#r{n}", "ocr": base[lo:hi], "anh_llm": text, "loai": "ap_lai",
                                 "quan_trong": bool(NUM_RE.findall(base[lo:hi])), "do_chac": "thap", "canh_bao": hints,
                                 "ly_do": "nguoi_da_duyet_nhung_khong_ap_duoc", "status": "pending_human", "sua_thanh": "",
                                 "nguon": None, "model": "chu_nguoi_da_go_truoc_do", "at": _now()}})
    return out


def build(cfg: dict | None = None, dry_run: bool = False) -> dict:
    items = plan(cfg)
    st = {"muc_moi": 0, "khong_dung_duoc": []}
    pages: dict[tuple, dict] = {}
    for x in items:
        if "loi" in x:
            st["khong_dung_duoc"].append(x["loi"])
            continue
        x["item"]["vi_tri"] = locate(x["pg"], x["item"]["ocr"], x["dpi"])
        st["muc_moi"] += 1
        if not dry_run:
            x["rec"]["items"].append(x["item"])
            pages.setdefault((x["layer"], x["pid"]), {"rec": x["rec"], "base": x["base"], "new": []})["new"].append(x["item"])
    if dry_run:
        return st
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    for (layer, pid), v in pages.items():
        _write(cleaner.LAYERS[layer], _refresh(v["rec"], v["base"]))
        staged = {k: v["rec"][k] for k in ("schema", "id", "file", "page", "extract_input_sha256", "base_text_sha256", "flags_goc", "rules", "llm")
                  if k in v["rec"]}
        staged.update(items=v["new"], corrected_text=v["base"], skipped_items=[], flags_after=[])
        _write(STAGE_DIR, staged)
    st["trang"] = len(pages)
    return st


def merge_back() -> dict:
    out = {}
    for layer, d in cleaner.LAYERS.items():
        out[layer] = merge_from(STAGE_DIR, d)
    return out

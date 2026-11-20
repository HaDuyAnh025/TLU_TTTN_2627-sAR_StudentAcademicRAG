"""Lớp HIỆU CHỈNH văn bản OCR: LLM tự sửa chỗ nó chắc chắn; chỗ còn lại do NGƯỜI sửa tay.

Thiết kế để vẫn giữ nguyên tắc "không động vào kết quả gốc":
  - data/interim/extract (kết quả OCR gốc) KHÔNG bao giờ bị sửa.
  - Mọi chỉnh sửa nằm ở lớp riêng data/interim/corrected/<trang>.json, mỗi chỗ ghi rõ: nguồn (llm | nguoi), đoạn gốc,
    đoạn sau sửa, lý do được tự sửa, trạng thái. Hoàn nguyên được từng chỗ.
  - `corrected_text` của trang KHÔNG gõ tay mà luôn tính lại từ văn bản gốc + danh sách chỉnh sửa; `corrections-verify` kiểm tra
    điều đó và mã băm niêm phong, nên sửa tay trực tiếp vào corrected_text sẽ bị phát hiện.
  - Cờ được gắn lại ở `flags_after`: llm_da_sua, can_nguoi_sua, nguoi_da_sua, llm_ra_soat_khong_loi (cờ gốc giữ ở `flags_goc`).

Quy trình (scripts/ingest.py):
  --stage llm-review         LLM rà soát, liệt kê chỗ khác nhau              → data/eval/llm_review/
  --stage corrections-build  áp quy tắc: chỗ nào LLM tự sửa, chỗ nào chờ người → data/interim/corrected/
  --stage corrections-queue  dựng trang web: các chỗ CẦN NGƯỜI SỬA + mẫu kiểm tra các chỗ LLM đã tự sửa
  --stage corrections-import đọc CSV bạn đã điền, cập nhật lớp hiệu chỉnh (người sửa; chỗ LLM sửa sai thì hoàn nguyên)
  --stage corrections-verify kiểm chứng tính toàn vẹn của lớp hiệu chỉnh
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from rag.config import EVAL_DIR, ROOT, load_config
from rag.evaluation.extract_eval import load_docs
from rag.evaluation.llm_review import LLM_DIR, build_items, page_key
from rag.evaluation.review_pack import wilson

CORR_DIR = ROOT / "data" / "interim" / "corrected"
QUEUE_DIR = EVAL_DIR / "corrections_queue"
SCHEMA = 1
FUZZY_APPLY = 90.0  # điểm khớp gần đúng tối thiểu để tự gán vị trí (settle)
NUM_RE = re.compile(r"\d+(?:[.,/:\-]\d+)*")
ACTIVE = ("applied", "human_applied")

DEFAULT_RULES = {
    "auto_min_confidence": "cao",          # chỉ tự sửa khi LLM tự đánh giá chắc chắn ở mức này
    "require_single_exact_match": True,    # đoạn gốc phải xuất hiện đúng 1 lần, khớp nguyên văn trong văn bản OCR
    "numbers_need_corroboration": True,    # lỗi số liệu: chuỗi số LLM đọc phải trùng với công cụ OCR thứ hai
    "max_len_ratio": 2.0,                  # đoạn sau sửa không dài/ngắn quá bất thường so với đoạn gốc
    "auto_audit_n": 20,                    # số chỗ LLM đã tự sửa đưa vào để người kiểm tra mẫu
    "apply_mode": "all",                   # all: LLM sửa MỌI chỗ áp dụng được, người duyệt sau (mặc định Đúng)
                                           # conservative: chỉ sửa chỗ đủ các điều kiện ở trên
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ áp chỉnh sửa (hàm xác định)
def apply_items(base: str, items: list[dict]) -> tuple[str, list[str]]:
    """Văn bản sau chỉnh sửa = văn bản gốc + các chỗ đang có hiệu lực. Chỗ không khớp duy nhất/chồng lấn bị bỏ qua và trả về id.
    Trường tùy chọn (do `settle` ghi, không đổi nội dung người đã duyệt): `ocr_khop` = đoạn đúng nguyên văn trong văn bản trang
    (khi đoạn `ocr` chỉ khác khoảng trắng/dấu |), `lan_thu` = lần xuất hiện (từ 0) khi đoạn lặp nhiều lần, `bo_qua_khi_ap` = lý do
    không cần thay (đã được mục khác thực hiện hoặc chữ sửa giống chữ OCR)."""
    spans = []
    skipped = []
    # hai mục trùng hệt vị trí: quyết định của người MỚI NHẤT thắng (mục duyệt lại thay mục cũ); sắp xếp ổn định ở dưới giữ thứ tự này
    for it in sorted(items, key=lambda x: x.get("at_nguoi") or x.get("at") or "", reverse=True):
        if it["status"] not in ACTIVE or it.get("bo_qua_khi_ap"):
            continue
        key = it.get("ocr_khop") or it["ocr"]
        n = base.count(key)
        k = it.get("lan_thu")  # đoạn gốc lặp nhiều lần: `lan_thu` (từ 0) chỉ rõ lần xuất hiện mà người đã xem và xác nhận
        if n != 1 and (k is None or not 0 <= k < n):
            skipped.append(it["item_id"])
            continue
        i = base.find(key)
        for _ in range((k or 0) if n != 1 else 0):
            i = base.find(key, i + len(key))
        spans.append((i, i + len(key), it["sua_thanh"], it["item_id"]))
    spans.sort(key=lambda x: (x[0], -x[1]))  # cùng điểm đầu: đoạn DÀI hơn được áp trước (nó bao trọn đoạn ngắn)
    out, pos, last_end = [], 0, 0
    for i, j, rep, iid in spans:
        if i < last_end:  # chồng lấn
            skipped.append(iid)
            continue
        out.append(base[pos:i])
        out.append(rep)
        pos, last_end = j, j
    out.append(base[pos:])
    return "".join(out), skipped


def flags_after(items: list[dict], llm_reviewed: bool) -> list[str]:
    """llm_da_sua = LLM sửa, người CHƯA duyệt; llm_sua_nguoi_xac_nhan = LLM sửa và người đã duyệt Đúng;
    nguoi_da_sua = người sửa; can_nguoi_sua = có chỗ chưa áp dụng được tự động, chờ người."""
    f = []
    if any(it["status"] in ("pending_human", "unapplicable") for it in items):
        f.append("can_nguoi_sua")
    if any(it["status"] == "applied" and not it.get("human_checked") for it in items):
        f.append("llm_da_sua")
    if any(it["status"] == "applied" and it.get("human_checked") for it in items):
        f.append("llm_sua_nguoi_xac_nhan")
    if any(it["status"] == "human_applied" for it in items):
        f.append("nguoi_da_sua")
    if llm_reviewed and not any(it["status"] != "no_change" for it in items):
        f.append("llm_ra_soat_khong_loi")
    return f


# ------------------------------------------------------------------ quy tắc tự sửa
def cross_numbers(pg: dict) -> set[str]:
    cc = (pg.get("raw") or {}).get("crosscheck")
    if not cc:
        return set()
    return {t for w in cc["words"] for t in NUM_RE.findall(w["text"])}


def decide(it: dict, base: str, pg: dict, rules: dict) -> tuple[bool, str]:
    ocr, anh = str(it.get("ocr", "")), str(it.get("anh", ""))
    if not ocr or anh == ocr:
        return False, "khong_co_thay_doi"
    if re.sub(r"[\s|]+", "", anh) == re.sub(r"[\s|]+", "", ocr) and not rules.get("allow_structure_only"):
        return False, "khong_co_thay_doi"  # chỉ khác khoảng trắng hoặc dấu | (cấu trúc cột), không phải lỗi chữ (rescan thì cho phép)
    if rules.get("apply_mode", "all") == "all":  # LLM sửa mọi chỗ áp dụng được; người duyệt sau
        n = base.count(ocr)
        if n != 1:
            return False, f"doan_goc_khop_{n}_lan"
        if it.get("doi_chieu"):  # chương trình đối chiếu lại với ảnh/văn bản thấy đáng ngờ → không tự áp, chờ người (rescan)
            return False, "doi_chieu_" + ",".join(it["doi_chieu"])
        return True, "llm_de_xuat_ap_dung"
    if it.get("do_chac") != rules["auto_min_confidence"]:
        return False, f"do_chac={it.get('do_chac')}"
    if rules["require_single_exact_match"] and base.count(ocr) != 1:
        return False, f"doan_goc_khop_{base.count(ocr)}_lan"
    r = len(anh) / max(len(ocr), 1)
    if r > rules["max_len_ratio"] or r < 1 / rules["max_len_ratio"]:
        return False, "do_dai_bat_thuong"
    nums = NUM_RE.findall(anh)
    if (it.get("loai") == "so_lieu" or nums != NUM_RE.findall(ocr)) and rules["numbers_need_corroboration"]:
        cn = cross_numbers(pg)
        if not nums or not cn or not all(n in cn for n in nums):
            return False, "so_lieu_chua_duoc_cong_cu_thu_hai_xac_nhan"
    return True, "du_dieu_kien_tu_dong"


# ------------------------------------------------------------------ ghi / đọc lớp
def _write(corr_dir: Path, rec: dict) -> None:
    corr_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(rec, ensure_ascii=False, indent=1).encode("utf-8")
    (corr_dir / f"{rec['id']}.json").write_bytes(data)
    (corr_dir / f"{rec['id']}.json.sha256").write_text(hashlib.sha256(data).hexdigest(), encoding="utf-8")


def _load(corr_dir: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(corr_dir.glob("*.json"))} if corr_dir.exists() else {}


def _refresh(rec: dict, base: str) -> dict:
    rec["corrected_text"], rec["skipped_items"] = apply_items(base, rec["items"])
    rec["flags_after"] = flags_after(rec["items"], True)
    rec["updated_at"] = _now()
    return rec


def build(cfg: dict | None = None, llm_dir: Path | None = None, corr_dir: Path | None = None, rules: dict | None = None,
          fresh: bool = False) -> dict:
    """fresh=True: bỏ qua lớp hiệu chỉnh đã có (MẤT các quyết định của người đã lưu) và dựng lại từ kết quả LLM."""
    cfg = cfg or load_config("ocr")
    rules = {**DEFAULT_RULES, **(rules or cfg.get("corrections", {}))}
    llm_dir, corr_dir = llm_dir or LLM_DIR, corr_dir or CORR_DIR
    index = {(d["file"], p["page"]): (d, p) for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    old = {} if fresh else _load(corr_dir)
    stats = {"pages": 0, "items": 0, "auto": 0, "human_queue": 0, "no_change": 0, "kept_existing": 0, "replaced_stale": 0}
    for jp in sorted(llm_dir.glob("*.json")):
        rec = json.loads(jp.read_text(encoding="utf-8"))
        if not rec.get("parse_ok"):
            continue
        got = index.get((rec["file"], rec["page"]))
        if not got:
            continue
        d, pg = got
        base = pg["derived"]["text"]
        prev = {it["item_id"]: it for it in old.get(rec["id"], {}).get("items", [])}
        items = []
        for k, it in enumerate(rec["loi"]):
            iid = f"{rec['id']}#{k}"
            if iid in prev:
                if prev[iid]["ocr"] == str(it.get("ocr", "")) and prev[iid]["anh_llm"] == str(it.get("anh", "")):
                    items.append(prev[iid])  # cùng nội dung → giữ quyết định đã có (kể cả của người)
                    stats["kept_existing"] += 1
                    continue
                stats["replaced_stale"] += 1  # trùng mã nhưng khác nội dung (kết quả LLM chạy lại) → không dùng kết quả cũ
            auto, why = decide(it, base, pg, rules)
            if auto:
                status = "applied"
            elif why == "khong_co_thay_doi":
                status = "no_change"
            elif why.startswith("doan_goc_khop"):
                status = "unapplicable"  # đoạn gốc không khớp đúng 1 lần → không thay tự động được, chờ người
            else:
                status = "pending_human"
            warn = []
            if it.get("do_chac") != "cao":
                warn.append("llm_chua_chac")
            if it.get("loai") in ("bang", "thua_dong", "thieu_dong"):
                warn.append("sua_cau_truc_bang_dong")
            ocr_s, anh_s = str(it.get("ocr", "")), str(it.get("anh", ""))
            if it.get("loai") == "so_lieu" or NUM_RE.findall(anh_s) != NUM_RE.findall(ocr_s):
                cn = cross_numbers(pg)
                nums = NUM_RE.findall(anh_s)
                if not nums or not cn or not all(n in cn for n in nums):
                    warn.append("so_lieu_chua_duoc_ocr_thu_hai_xac_nhan")
            items.append({"item_id": iid, "ocr": str(it.get("ocr", "")), "anh_llm": str(it.get("anh", "")),
                          "loai": it.get("loai", ""), "quan_trong": bool(it.get("quan_trong")), "do_chac": it.get("do_chac", ""),
                          "canh_bao": warn, "vi_tri": it.get("vi_tri"), "ly_do": why, "status": status,
                          "sua_thanh": str(it.get("anh", "")) if auto else "", "nguon": "llm" if auto else None,
                          "model": rec.get("model"), "at": _now()})
            stats["auto" if auto else ("no_change" if status == "no_change" else "human_queue")] += 1
        stats["items"] += len(items)
        stats["pages"] += 1
        out = {"schema": SCHEMA, "id": rec["id"], "file": rec["file"], "page": rec["page"],
               "extract_input_sha256": d["input_sha256"], "base_text_sha256": sha(base), "flags_goc": pg["quality"]["flags"],
               "rules": rules, "llm": {"provider": rec.get("provider"), "model": rec.get("model"),
                                       "prompt_sha256": rec.get("prompt_sha256")},
               "items": items}
        _write(corr_dir, _refresh(out, base))
    return stats


# ------------------------------------------------------------------ hàng đợi cho người
def queue(cfg: dict | None = None, llm_dir: Path | None = None, corr_dir: Path | None = None, out_dir: Path | None = None,
          seed: int = 42) -> dict:
    cfg = cfg or load_config("ocr")
    rules = {**DEFAULT_RULES, **cfg.get("corrections", {})}
    corr_dir = corr_dir or CORR_DIR
    pend, auto = set(), []
    for rec in _load(corr_dir).values():
        for it in rec["items"]:
            if it["status"] == "pending_human":
                pend.add(it["item_id"])
            elif it["status"] == "applied" and not it.get("human_checked"):
                auto.append(it["item_id"])
    random.Random(seed).shuffle(auto)
    auto_sel = set(auto[: rules["auto_audit_n"]])
    meta = build_items(cfg, audit_n=0, llm_dir=llm_dir or LLM_DIR, items_dir=out_dir or QUEUE_DIR,
                       only_items=pend, auto_items=auto_sel)
    meta.update({"cho_nguoi_sua": len(pend), "tu_dong_da_sua_tong": len(auto), "tu_dong_dua_vao_kiem_tra": len(auto_sel)})
    return meta


# ------------------------------------------------------------------ nhập kết quả của người
def import_human(cfg: dict | None = None, csv_path: str | Path | None = None, corr_dir: Path | None = None,
                 queue_dir: Path | None = None) -> dict:
    cfg = cfg or load_config("ocr")
    corr_dir, queue_dir = corr_dir or CORR_DIR, queue_dir or QUEUE_DIR
    csv_path = Path(csv_path) if csv_path else queue_dir / "review_items_filled.csv"
    if not csv_path.exists():
        raise SystemExit(f"Chưa có file đã điền: {csv_path}")
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    layer = _load(corr_dir)
    st = {"nguoi_chap_nhan_llm": 0, "nguoi_tu_sua": 0, "giu_nguyen_ocr": 0, "chua_ro": 0, "khong_ap_duoc": 0,
          "llm_sua_dung": 0, "llm_sua_sai_hoan_nguyen": 0, "audit_khong_ro": 0}
    touched = set()
    for r in csv.DictReader(csv_path.open(encoding="utf-8-sig")):
        nhan = (r.get("nhan") or "").strip()
        if not nhan or r["kind"] not in ("item", "auto"):
            continue
        rec = layer.get(r["trang_id"])
        it = next((x for x in rec["items"] if x["item_id"] == r["item_id"]), None) if rec else None
        if not it:
            continue
        touched.add(r["trang_id"])
        if r["kind"] == "auto":
            if nhan == "dung":
                it["human_checked"], st["llm_sua_dung"] = True, st["llm_sua_dung"] + 1
            elif nhan == "sai":
                it["status"], it["nguon"], it["human_checked"] = "reverted", None, True
                st["llm_sua_sai_hoan_nguyen"] += 1
            else:
                st["audit_khong_ro"] += 1
            continue
        if nhan == "llm_dung":
            it.update(status="human_applied", sua_thanh=it["anh_llm"], nguon="nguoi_chap_nhan_llm", at=_now())
            st["nguoi_chap_nhan_llm"] += 1
        elif nhan == "ca_hai_sai" and (r.get("sua_thanh") or "").strip():
            it.update(status="human_applied", sua_thanh=r["sua_thanh"].strip(), nguon="nguoi", at=_now())
            st["nguoi_tu_sua"] += 1
        elif nhan == "ocr_dung":
            it.update(status="kept_ocr", nguon=None, at=_now())
            st["giu_nguyen_ocr"] += 1
        else:
            st["chua_ro"] += 1
    for pid in touched:
        rec = layer[pid]
        pg = index[(rec["file"], rec["page"])]
        base = pg["derived"]["text"]
        _refresh(rec, base)
        st["khong_ap_duoc"] += len(rec["skipped_items"])
        _write(corr_dir, rec)
    return st


# ------------------------------------------------------------------ kiểm chứng
def verify_layer(cfg: dict | None = None, corr_dir: Path | None = None) -> dict:
    cfg = cfg or load_config("ocr")
    corr_dir = corr_dir or CORR_DIR
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    prob = {"bi_sua_sau_khi_ghi": [], "van_ban_goc_da_doi": [], "corrected_text_lech": [], "cờ_lech": [], "khong_thay_trang": []}
    n = 0
    for p in sorted(corr_dir.glob("*.json")) if corr_dir.exists() else []:
        n += 1
        seal = corr_dir / f"{p.name}.sha256"
        if not seal.exists() or seal.read_text(encoding="utf-8").strip() != hashlib.sha256(p.read_bytes()).hexdigest():
            prob["bi_sua_sau_khi_ghi"].append(p.name)
        rec = json.loads(p.read_text(encoding="utf-8"))
        pg = index.get((rec["file"], rec["page"]))
        if not pg:
            prob["khong_thay_trang"].append(p.name)
            continue
        base = pg["derived"]["text"]
        if sha(base) != rec["base_text_sha256"]:
            prob["van_ban_goc_da_doi"].append(p.name)
        text, _ = apply_items(base, rec["items"])
        if text != rec["corrected_text"]:
            prob["corrected_text_lech"].append(p.name)
        if flags_after(rec["items"], True) != rec["flags_after"]:
            prob["cờ_lech"].append(p.name)
    return {"ok": not any(prob.values()), "pages": n, "problems": prob}


def summarize(corr_dir: Path | None = None) -> dict:
    from collections import Counter
    c = Counter()
    for rec in _load(corr_dir or CORR_DIR).values():
        for it in rec["items"]:
            c[it["status"]] += 1
        for f in rec["flags_after"]:
            c["trang:" + f] += 1
    return dict(c)


def merge_from(other_dir: Path, corr_dir: Path | None = None, cfg: dict | None = None) -> dict:
    """Gộp quyết định của người khác (thư mục data/interim/corrected của máy họ) vào lớp hiệu chỉnh này.
    Chỉ lấy các chỗ người ĐÃ duyệt (human_checked); chỗ nào bên này đã duyệt khác bên kia thì giữ bên này và báo xung đột.
    Văn bản sau sửa được dựng lại bằng hàm xác định; không đụng data/interim/extract."""
    from rag.evaluation.extract_eval import load_docs
    cfg = cfg or load_config("ocr")
    corr_dir = corr_dir or CORR_DIR
    base = {(d["file"], p["page"]): p["derived"]["text"] for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    mine, theirs = _load(corr_dir), _load(other_dir)
    st = {"trang_ben_kia": len(theirs), "trang_cap_nhat": 0, "cho_nhan_ve": 0, "xung_dot_giu_ben_nay": 0, "khong_co_trang": 0}
    for pid, rec in theirs.items():
        if pid not in mine:
            st["khong_co_trang"] += 1
            continue
        local = mine[pid]
        where = {it["item_id"]: it for it in local["items"]}
        changed = False
        for it in rec["items"]:
            if not it.get("human_checked") or it["item_id"] not in where:
                continue
            cur = where[it["item_id"]]
            if cur.get("human_checked"):
                if cur != it:
                    st["xung_dot_giu_ben_nay"] += 1
                continue
            cur.clear()
            cur.update(it)
            st["cho_nhan_ve"] += 1
            changed = True
        if changed:
            _refresh(local, base[(local["file"], local["page"])])
            _write(corr_dir, local)
            st["trang_cap_nhat"] += 1
    return st


# ------------------------------------------------------------------ xử lý chỗ người đã duyệt nhưng chưa thay vào văn bản được
def _occurrences(base: str, s: str) -> list[int]:
    out, i = [], base.find(s)
    while i >= 0:
        out.append(i)
        i = base.find(s, i + len(s))
    return out


def _word_edge(base: str, a: int, b: int) -> bool:
    left = base[a - 1] if a > 0 else " "
    right = base[b] if b < len(base) else " "
    return not (left.isalnum() and base[a].isalnum()) and not (right.isalnum() and base[b - 1].isalnum())


def settle(cfg: dict | None = None, corr_dir: Path | None = None, dry_run: bool = False) -> dict:
    """Với chỗ NGƯỜI ĐÃ DUYỆT, đang có hiệu lực nhưng `apply_items` không thay được: xác định cách thay đúng, bằng quy tắc xác định.
    Không đổi chữ người đã duyệt (sua_thanh); chỉ ghi thêm trường chỉ vị trí/lý do:
      - đoạn gốc không có nguyên văn:  chữ sửa giống chữ OCR → `bo_qua_khi_ap` (không cần thay); hoặc đoạn khớp DUY NHẤT khi bỏ
        khoảng trắng/dấu | → `ocr_khop` (đoạn đúng nguyên văn trong trang)
      - đoạn gốc lặp nhiều lần: `lan_thu` = lần xuất hiện mà ảnh người đã xem hiển thị (khớp đầu tiên của locate); mục trùng hệt gán
        lần lượt các lần kế tiếp. Không gán khi đoạn ≤3 ký tự, lọt giữa từ/số khác, chữ sửa đã có sẵn, hoặc vị trí không khớp.
      - chồng lấn: nếu chữ sửa của mục bị bỏ đã có trong kết quả → `bo_qua_khi_ap`; nếu mục bị bỏ BAO TRỌN mục đã áp và chữ sửa của
        mục đã áp nằm trong chữ sửa của nó → mục nhỏ `bo_qua_khi_ap` để mục lớn được áp. Còn lại để nguyên, báo là xung đột."""
    from rag.evaluation.llm_review import _squash_map, _text_with_spans
    cfg = cfg or load_config("ocr")
    corr_dir = corr_dir or CORR_DIR
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    st: dict[str, int] = {}

    def bump(k: str) -> None:
        st[k] = st.get(k, 0) + 1

    left = []
    for rec in _load(corr_dir).values():
        pg = index[(rec["file"], rec["page"])]
        base = pg["derived"]["text"]
        norm, idx = _squash_map(base)
        text_ok = bool(pg["raw"].get("words")) and pg["route"] == "ocr" and _text_with_spans(pg["raw"]["words"])[0] == base
        taken: dict[str, set] = {}
        changed = False
        hum = [it for it in rec["items"] if it["status"] in ACTIVE and it.get("human_checked")]
        for it in hum:
            if it.get("bo_qua_khi_ap") or it.get("ocr_khop") or it.get("lan_thu") is not None:
                continue
            ocr, anh = it["ocr"], it["sua_thanh"]
            n = base.count(ocr)
            if n == 1:
                continue
            sq = _squash_map(ocr)[0].strip()
            if n == 0:
                if sq and _squash_map(anh)[0].strip() == sq:
                    it["bo_qua_khi_ap"] = "chu_sua_giong_chu_ocr"
                    bump("khong_can_thay_chu_sua_giong_ocr")
                    changed = True
                elif sq and norm.count(sq) == 1:
                    pos = norm.find(sq)
                    it["ocr_khop"] = base[idx[pos]: idx[pos + len(sq) - 1] + 1]
                    bump("khop_mem_duy_nhat")
                    changed = True
                else:
                    al = fuzz.partial_ratio_alignment(ocr, base)  # khớp gần đúng rất cao (≥90): lấy đúng đoạn trong trang đó
                    sub = base[al.dest_start:al.dest_end]
                    if al.score >= FUZZY_APPLY and sub and base.count(sub) == 1 and _word_edge(base, al.dest_start, al.dest_end):
                        it["ocr_khop"], it["khop_gan_dung"] = sub, round(al.score, 1)
                        bump("khop_gan_dung_ge_90")
                        changed = True
                    else:
                        left.append((it["item_id"], "khong_tim_thay_doan_goc"))
                continue
            if sq and _squash_map(anh)[0].strip() == sq:  # chữ sửa giống chữ OCR (giữ nguyên): không cần thay chỗ nào
                it["bo_qua_khi_ap"] = "chu_sua_giong_chu_ocr"
                bump("khong_can_thay_chu_sua_giong_ocr")
                changed = True
                continue
            occ = _occurrences(base, ocr)
            why = None
            pos = norm.find(sq) if sq else -1
            a0 = idx[pos] if pos >= 0 else -1
            if not text_ok:
                why = "khong_dung_lai_duoc_vi_tri_hien_thi"
            elif a0 not in occ:
                why = "vi_tri_hien_thi_khong_khop_lan_nao"
            elif len(ocr.strip()) <= 3:
                why = "doan_ngan_lap_lai"
            else:
                order = occ[occ.index(a0):] + occ[:occ.index(a0)]
                used = taken.setdefault(ocr + "\x00" + anh, set())
                k = next((i for i in order if i not in used), None)
                if k is None:
                    why = "het_lan_xuat_hien_de_gan"
                elif not _word_edge(base, k, k + len(ocr)):
                    why = "doan_lot_giua_tu_hoac_so"
                elif (anh and base[k:k + len(anh)] == anh) or (anh.startswith(ocr) and base[k + len(ocr):].startswith(anh[len(ocr):])):
                    why = "cho_sua_da_co_san"
                else:
                    used.add(k)
                    it["lan_thu"] = occ.index(k)
                    bump("gan_lan_xuat_hien")
                    changed = True
            if why:
                left.append((it["item_id"], why))
        # chồng lấn
        _, sk = apply_items(base, hum)
        for iid in list(sk):
            b = next(x for x in hum if x["item_id"] == iid)
            if base.count(b.get("ocr_khop") or b["ocr"]) == 0:
                continue
            out, sk_now = apply_items(base, hum)
            if iid not in sk_now:
                continue
            if _squash_map(b["sua_thanh"])[0].strip() and _squash_map(b["sua_thanh"])[0].strip() in _squash_map(out)[0]:
                b["bo_qua_khi_ap"] = "da_thuc_hien_boi_muc_khac"
                bump("chong_lan_da_thuc_hien")
                changed = True
                continue
            key = b.get("ocr_khop") or b["ocr"]
            bi = base.find(key)
            if base.count(key) != 1 and b.get("lan_thu") is None:
                continue
            inner = []
            for a in hum:
                if a is b or a["item_id"] in sk_now or a.get("bo_qua_khi_ap"):
                    continue
                ak = a.get("ocr_khop") or a["ocr"]
                if base.count(ak) == 1 and bi <= base.find(ak) and base.find(ak) + len(ak) <= bi + len(key):
                    inner.append(a)
            if inner and all(_squash_map(a["sua_thanh"])[0].strip() in _squash_map(b["sua_thanh"])[0] for a in inner):
                for a in inner:
                    a["bo_qua_khi_ap"] = "gop_vao_" + b["item_id"]
                _, sk2 = apply_items(base, hum)
                if iid in sk2:  # vẫn không áp được → hoàn tác
                    for a in inner:
                        a.pop("bo_qua_khi_ap", None)
                    left.append((iid, "chong_lan_xung_dot"))
                else:
                    bump("chong_lan_muc_lon_thay_muc_nho")
                    changed = True
            else:
                left.append((iid, "chong_lan_xung_dot"))
        if changed and not dry_run:
            _write(corr_dir, _refresh(rec, base))
    rest = {}
    for _, why in left:
        rest[why] = rest.get(why, 0) + 1
    return {"da_xu_ly": st, "con_lai": rest, "chi_tiet_con_lai": left}


def promote_confirmed(corr_dir: Path | None = None, dry_run: bool = False) -> dict:
    """Mục NGƯỜI ĐÃ BẤM ĐÚNG (human_checked) nhưng `accept()` cũ chỉ ghi `unapplicable` vì đoạn gốc không khớp đúng 1 lần: đưa về
    `human_applied` với chữ sửa = đúng đề xuất LLM mà người đã xác nhận. Việc tìm vị trí để thay do `settle` làm sau đó.
    Mục LLM đề xuất không đổi gì (anh_llm = ocr) thì chỉ đánh dấu `bo_qua_khi_ap`."""
    cfg = load_config("ocr")
    index = {(d["file"], p["page"]): p["derived"]["text"] for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    st = {"nang_len": 0, "khong_doi_gi": 0}
    for rec in _load(corr_dir or CORR_DIR).values():
        changed = False
        for it in rec["items"]:
            if it["status"] != "unapplicable" or not it.get("human_checked"):
                continue
            if it["anh_llm"] == it["ocr"]:
                st["khong_doi_gi"] += 1
                continue
            it.update(status="human_applied", sua_thanh=it["anh_llm"], nguon="nguoi", llm_da_de_xuat=it["anh_llm"],
                      sua_chua="nguoi_bam_dung_nhung_chua_ap_dung")
            st["nang_len"] += 1
            changed = True
        if changed and not dry_run:
            _write(corr_dir or CORR_DIR, _refresh(rec, index[(rec["file"], rec["page"])]))
    return st

"""(TÙY CHỌN) VLM đọc lại các trang ctdt nghi có bảng -> lớp mới data/interim/table_vlm/<doc_id>.json.

Nguyên tắc:
  - KHÔNG sửa clean/ hay bất kỳ lớp interim nào có sẵn; chỉ ghi vào data/interim/table_vlm/ và data/processed/table_vlm_check.csv.
  - Cùng schema `pages[]` như clean/ nhưng chỉ chứa trang đã đọc lại; `page` là chỉ số 0-based (đúng như clean/),
    nguon_van_ban = "vlm_table". Văn bản do mô hình SINH, nên mỗi trang có kiểm tra tự động; trang `need_review` không được loader dùng.
  - Gọi API theo đúng cách của rag.ingestion.vlm_ocr (nhà cung cấp/mô hình/detail/max_side lấy từ configs/ocr.yaml: vlm.*).
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime
from pathlib import Path

from rag.config import ROOT, chunking_config, load_config
from rag.ingestion.loader import FILES_DIR
from rag.ingestion.ocr_engines import render_pdf_page
from rag.ingestion.vlm_ocr import _load_env, _to_jpeg_b64, model_ready

log = logging.getLogger("table_vlm")
SPOT_MIN_ONLY_VLM = 5  # >= ngần này số/mã chỉ có ở VLM -> spot_check (vẫn được dùng)

NUM_RE = re.compile(r"\d+(?:[.,/:\-]\d+)*")
CODE_RE = re.compile(r"(?<![\w])[A-ZĐ]{2,5}\s?\d{2,4}(?![\w])")
SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def tokens_of(text: str) -> set[str]:
    """Tập các con số và mã học phần (chữ+số, bỏ khoảng trắng giữa chữ và số) trong văn bản."""
    out = {re.sub(r"^(\d+),(\d{1,2})$", r"\1.\2", m.group(0).strip(",.")) for m in NUM_RE.finditer(text)}  # 4,0 == 4.0
    out |= {re.sub(r"\s", "", m.group(0)) for m in CODE_RE.finditer(text)}
    return {t for t in out if t}


def _cells(line: str) -> int:
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return len(re.split(r"(?<!\\)\|", s))


def check_tables(md: str) -> tuple[int, bool, str]:
    """(số bảng, hợp lệ?, lý do). Hợp lệ: có >= 1 bảng, mỗi bảng có dòng phân cách ngay sau header và mọi dòng cùng số cột."""
    lines = md.split("\n")
    blocks, cur = [], []
    for l in lines:
        if l.lstrip().startswith("|"):
            cur.append(l)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    if not blocks:
        return 0, True, "khong_co_bang"  # không có bảng thì không có bảng nào sai; chỉ ghi chú (trang bị OCR nghi nhầm là bảng)
    for n, b in enumerate(blocks, 1):
        if len(b) < 2 or not SEP_RE.match(b[1]):
            return len(blocks), False, f"bang{n}:thieu_dong_phan_cach"
        widths = {_cells(l) for i, l in enumerate(b) if i != 1}
        if len(widths) != 1 or _cells(b[1]) != next(iter(widths)):
            return len(blocks), False, f"bang{n}:so_cot_khong_deu({sorted(widths)})"
    return len(blocks), True, ""


def check_page(md: str, old_text: str, min_match: float, md_raw: str | None = None) -> dict:
    """Kiểm tra một trang VLM. Số/mã so với OCR cũ tính trên bản gốc của mô hình (md_raw); bảng kiểm tra trên bản cuối (md)."""
    v, o = tokens_of(md_raw if md_raw is not None else md), tokens_of(old_text)
    inter = v & o
    n_tables, valid, issue = check_tables(md)
    rate = len(inter) / len(v) if v else 0.0
    return {"n_tokens_vlm": len(v), "n_tokens_ocr": len(o), "match_rate": round(rate, 3),
            "recall_vs_ocr": round(len(inter) / len(o), 3) if o else 0.0,
            "ocr_recall": round(len(inter) / len(o), 3) if o else 0.0,  # tỉ lệ số/mã của OCR cũ có trong bản VLM (thấp -> nghi VLM bỏ sót)
            "only_in_vlm": sorted(v - o)[:40], "n_only_in_vlm": len(v - o), "spot_check": len(v - o) >= SPOT_MIN_ONLY_VLM,
            "n_tables": n_tables, "table_valid": valid, "table_issue": issue, "n_unknown": md.count("[?]"),
            "need_review": (rate < min_match) or (not valid)}


# ------------------------------------------------------------------------------------------------ dòng bảng thiếu "|"
ROW_NO_PIPE = re.compile(r"^[A-Z]{2,4}\d{2,3}\s*\|")
SEP_ANY = re.compile(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*")  # "---|---|---" có hoặc không có | ở hai đầu


def add_edge_pipes(text: str) -> tuple[str, int]:
    """Khối >= 2 dòng liên tiếp, mỗi dòng có >= 2 dấu "|" và có một dòng phân cách `---|---`: thêm "| " ở đầu và " |" ở cuối mọi dòng
    của khối còn thiếu (bảng Markdown viết không có | ở hai đầu). Trả (văn bản mới, số dòng đã sửa)."""
    lines = text.split("\n")
    n, i = 0, 0
    while i < len(lines):
        j = i
        while j < len(lines) and lines[j].count("|") >= 2:
            j += 1
        if j - i >= 2 and any(SEP_ANY.fullmatch(l) for l in lines[i:j]):
            for k in range(i, j):
                st = lines[k].strip()
                if SEP_ANY.fullmatch(st):  # dòng phân cách dựng lại gọn: |---|---|---|
                    new = "|" + "|".join(c.strip() for c in st.strip("|").split("|")) + "|"
                else:
                    new = ("" if st.startswith("|") else "| ") + st + ("" if st.endswith("|") else " |")
                if new != lines[k]:
                    lines[k] = new
                    n += 1
            w = _cells(lines[i])  # dòng nhãn nhóm thiếu ô trống ở cuối so với header: bù ô trống (không thêm chữ)
            for k in range(i + 2, j):
                if not SEP_ANY.fullmatch(lines[k].strip()) and 1 <= _cells(lines[k]) < w:
                    lines[k] += "  |" * (w - _cells(lines[k]))
        i = max(j, i + 1)
    return "\n".join(lines), n


def normalize_rows(text: str) -> tuple[str, int]:
    r"""Dòng khớp `^[A-Z]{2,4}\d{2,3}\s*\|` mà không bắt đầu bằng "|": thêm "| " ở đầu (và " |" ở cuối nếu thiếu) khi số cột
    bằng số cột của dòng bảng liền trước hoặc liền sau. Trả (văn bản mới, số dòng đã sửa)."""
    text, n = add_edge_pipes(text)  # bảng viết không có "|" ở hai đầu dòng: sửa trước, rồi mới xét dòng mã lẻ
    lines = text.split("\n")
    for i, l in enumerate(lines):
        if l.lstrip().startswith("|") or not ROW_NO_PIPE.match(l):
            continue
        st = l.strip()
        new = "| " + st + ("" if st.endswith("|") else " |")
        adj = {_cells(lines[j]) for j in (i - 1, i + 1) if 0 <= j < len(lines) and lines[j].lstrip().startswith("|")}
        if _cells(new) in adj:
            lines[i] = new
            n += 1
    return "\n".join(lines), n


# ------------------------------------------------------------------------------------------------ bảng tiếp nối
def _blocks(text: str) -> list[list[str]]:
    out, cur = [], []
    for l in text.split("\n"):
        if l.lstrip().startswith("|"):
            cur.append(l)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def headerless_continuation(text: str) -> int | None:
    """Số cột nếu trang MỞ ĐẦU bằng các dòng "|" không có dòng phân cách |---| (bảng tiếp nối từ trang trước); ngược lại None."""
    lines = text.lstrip("\n").split("\n")
    if not lines or not lines[0].lstrip().startswith("|"):
        return None
    if len(lines) > 1 and SEP_RE.match(lines[1]):
        return None
    return _cells(lines[0])


def last_header(text: str) -> tuple[str, str, int] | None:
    """(dòng header, dòng phân cách, số cột) của bảng CUỐI trang; None nếu bảng cuối không có header + phân cách."""
    bl = _blocks(text)
    if not bl or len(bl[-1]) < 2 or not SEP_RE.match(bl[-1][1]):
        return None
    return bl[-1][0], bl[-1][1], _cells(bl[-1][0])


def has_table_text(text: str) -> bool:
    """Trang có bảng: có dòng phân cách |---| hoặc >= 4 dòng "|" liên tiếp (bảng OCR chưa dựng)."""
    return any(SEP_RE.match(l) and "|" in l for l in text.split("\n")) or any(len(b) >= 4 for b in _blocks(text))


# ------------------------------------------------------------------------------------------------ gọi API
class Temperature:
    """temperature=0 nếu mô hình hỗ trợ; không hỗ trợ thì bỏ tham số và ghi rõ vào log + vào params của từng trang."""

    supported: bool | None = None


def transcribe(img, vcfg: dict, prompt: str, max_tokens: int) -> tuple[str, dict]:
    """Như vlm_ocr.transcribe_openai nhưng temperature=0 (nếu hỗ trợ), trả thêm finish_reason và token suy luận; thử lại khi lỗi tạm thời."""
    from openai import BadRequestError, OpenAI
    oc = vcfg.get("openai") or {}
    url = "data:image/jpeg;base64," + _to_jpeg_b64(img, vcfg["max_side"])
    kw = dict(model=oc["model"], max_completion_tokens=max_tokens,
              messages=[{"role": "user", "content": [{"type": "text", "text": prompt},
                                                      {"type": "image_url", "image_url": {"url": url, "detail": "high"}}]}])
    client = OpenAI()
    for attempt in range(4):
        try:
            if Temperature.supported is not False:
                try:
                    resp = client.chat.completions.create(temperature=0, **kw)
                    Temperature.supported = True
                except BadRequestError as e:
                    if "temperature" not in str(e).lower():
                        raise
                    Temperature.supported = False
                    log.warning("mô hình %s không hỗ trợ temperature=0: gọi không đặt temperature (ghi vào params từng trang)", oc["model"])
                    resp = client.chat.completions.create(**kw)
            else:
                resp = client.chat.completions.create(**kw)
            break
        except BadRequestError:
            raise
        except Exception as e:  # noqa: BLE001  (giới hạn tốc độ, lỗi mạng tạm thời)
            if attempt == 3:
                raise
            log.warning("lỗi tạm thời (%s), thử lại lần %d", type(e).__name__, attempt + 1)
            time.sleep(5 * (attempt + 1))
    ch, u = resp.choices[0], resp.usage
    det = getattr(u, "completion_tokens_details", None)
    usage = {"input_tokens": getattr(u, "prompt_tokens", None), "output_tokens": getattr(u, "completion_tokens", None),
             "reasoning_tokens": getattr(det, "reasoning_tokens", None) if det else None, "finish_reason": ch.finish_reason}
    return (ch.message.content or "").strip(), usage


class Ctx:
    """Cấu hình + dữ liệu clean dùng chung cho một lần chạy."""

    def __init__(self) -> None:
        self.cc = chunking_config()
        self.t = self.cc["table_vlm"]
        self.v = load_config("ocr")["vlm"]
        self.prov, self.model, has_key, env_name, _ = model_ready(self.v)
        if self.prov != "openai" or not has_key or not self.model:
            raise SystemExit(f"Cần provider=openai, mô hình và khóa {env_name} (configs/ocr.yaml, .env); hiện: {self.prov}/{self.model}/{has_key}")
        self.sha = hashlib.sha256(self.t["prompt"].encode("utf-8")).hexdigest()
        self.out: Path = self.cc["paths"]["table_vlm_dir"]
        self.out.mkdir(parents=True, exist_ok=True)
        self.usage_log: Path = self.cc["paths"]["out_dir"] / "table_vlm_usage.jsonl"
        self.clean: dict[str, dict] = {}
        for p in sorted(self.cc["paths"]["clean_dir"].glob("*.json")):
            if p.name != "_manifest.json":
                d = json.loads(p.read_text(encoding="utf-8"))
                self.clean[Path(d["file"]).stem] = d

    def params(self) -> dict:
        ok = Temperature.supported is not False
        return {"provider": self.prov, "model": self.model, "detail": "high", "max_side": self.v["max_side"], "jpeg_quality": 88,
                "render_dpi": self.t["render_dpi"], "max_completion_tokens": self.t["max_tokens"],
                "temperature": 0 if ok else None,
                "temperature_note": None if ok else "mô hình không hỗ trợ temperature=0: dùng mặc định của API"}

    def page(self, doc_id: str, p0: int) -> dict | None:
        return next((p for p in self.clean[doc_id]["pages"] if p["page"] == p0), None)

    def load(self, doc_id: str) -> dict:
        f = self.out / f"{doc_id}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {
            "schema": 1, "file": self.clean[doc_id]["file"], "source": "table_vlm", "pages": []}

    def save(self, doc_id: str, rec: dict) -> None:
        rec["pages"].sort(key=lambda p: p["page"])
        (self.out / f"{doc_id}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

    def done(self, rec: dict, p0: int) -> bool:
        return any(p["page"] == p0 and p.get("prompt_sha256") == self.sha and "params" in p for p in rec["pages"])


def read_one(ctx: Ctx, doc_id: str, p0: int) -> dict:
    """Đọc lại một trang bằng VLM, trả bản ghi trang (chưa xử lý bảng tiếp nối)."""
    data, pg = ctx.clean[doc_id], ctx.page(doc_id, p0)
    img = render_pdf_page(FILES_DIR / data["file"], p0, ctx.t["render_dpi"])
    md, usage = transcribe(img, ctx.v, ctx.t["prompt"], ctx.t["max_tokens"])
    chk = check_page(md, pg["text"], ctx.t["min_match_rate"])
    if usage["finish_reason"] != "stop":
        chk["need_review"] = True
        chk["table_issue"] = (chk["table_issue"] + ";" if chk["table_issue"] else "") + f"finish={usage['finish_reason']}"
    now = datetime.now().isoformat(timespec="seconds")
    with ctx.usage_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"doc_id": doc_id, "page": p0 + 1, "at": now, **usage}, ensure_ascii=False) + "\n")
    return {"page": p0, "route": "ocr", "nguon_van_ban": "vlm_table", "lop": "table_vlm", "model": ctx.model, "params": ctx.params(),
            "prompt_sha256": ctx.sha, "generated_at": now, "usage": usage, "check": chk, "need_review": chk["need_review"],
            "text_vlm_raw": md, "text": md}


def reprocess_page(ctx: Ctx, doc_id: str, p: dict, stats: dict) -> None:
    """Dựng lại `text` của trang từ bản gốc của mô hình: chuẩn hóa dòng thiếu "|" rồi tính lại kiểm tra. Bước gắn header chạy sau đó."""
    base, n = normalize_rows(p["text_vlm_raw"])
    p["rows_fixed"], p["text"] = n, base
    p.pop("continued_header", None)
    p.pop("continued_from_page", None)
    chk = check_page(base, ctx.page(doc_id, p["page"])["text"], ctx.t["min_match_rate"], base)
    if p["usage"]["finish_reason"] != "stop":
        chk["need_review"] = True
    p["check"], p["need_review"] = chk, chk["need_review"]
    stats["rows_fixed"] = stats.get("rows_fixed", 0) + n


def finalize_doc(ctx: Ctx, doc_id: str, rec: dict, stats: dict) -> None:
    """Gắn header + dòng phân cách của bảng trang liền trước vào trang tiếp nối (continued_header=true); đọc thêm trang trước nếu cần."""
    tried: set[int] = set()
    while True:
        todo = [p for p in rec["pages"] if "continued_header" not in p]
        if not todo:
            return
        pg = min(todo, key=lambda p: p["page"])
        nc = headerless_continuation(pg["text"])
        if nc is None:
            pg["continued_header"] = False
            continue
        prev0 = pg["page"] - 1
        prev_rec = next((p for p in rec["pages"] if p["page"] == prev0), None)
        prev_clean = ctx.page(doc_id, prev0)
        prev_text = prev_rec["text"] if prev_rec else (prev_clean["text"] if prev_clean else "")
        hdr = last_header(prev_text)
        if hdr and hdr[2] == nc:
            base = pg["text"]  # đã chuẩn hóa dòng thiếu "|" (reprocess_page)
            pg["text"] = f"{hdr[0]}\n{hdr[1]}\n{base.lstrip(chr(10))}"
            pg["continued_header"], pg["continued_from_page"] = True, prev0 + 1
            chk = check_page(pg["text"], ctx.page(doc_id, pg["page"])["text"], ctx.t["min_match_rate"], base)
            if pg["usage"]["finish_reason"] != "stop":
                chk["need_review"] = True
            pg["check"], pg["need_review"] = chk, chk["need_review"]
            stats["continued_header"] += 1
            continue
        if prev_rec is None and prev_clean and prev_clean["route"] == "ocr" and has_table_text(prev_clean["text"]) and prev0 not in tried:
            tried.add(prev0)  # trang trước chứa bảng nhưng chưa nằm trong danh sách: thêm vào danh sách đọc lại
            print(f"  + thêm trang trước {doc_id} trang {prev0 + 1} (bảng tiếp nối của trang {pg['page'] + 1})")
            newp = read_one(ctx, doc_id, prev0)
            reprocess_page(ctx, doc_id, newp, stats)
            rec["pages"].append(newp)
            stats["added_prev"] += 1
            ctx.save(doc_id, rec)
            continue
        pg["continued_header"] = False  # không gắn được header: giữ nguyên check (bảng thiếu dòng phân cách -> need_review)


def read_pages(targets: list[tuple[str, int]], workers: int = 6) -> dict:
    """Đọc lại các trang [(doc_id, trang 1-based)] song song, rồi xử lý bảng tiếp nối theo thứ tự trang. Trả thống kê."""
    ctx = Ctx()
    stats = {"pages_read": 0, "continued_header": 0, "added_prev": 0, "errors": 0, "rows_fixed": 0}
    recs: dict[str, dict] = {}
    jobs = []
    for doc_id, page1 in targets:
        recs.setdefault(doc_id, ctx.load(doc_id))
        if not ctx.done(recs[doc_id], page1 - 1):
            jobs.append((doc_id, page1 - 1))
    print(f"{len(targets)} trang trong danh sách, {len(jobs)} trang cần gọi API")
    if jobs:
        # gọi trang đầu đơn lẻ để xác định mô hình có hỗ trợ temperature=0 (ghi log) trước khi chạy song song
        d0, p0 = jobs[0]
        recs[d0]["pages"] = [p for p in recs[d0]["pages"] if p["page"] != p0] + [read_one(ctx, d0, p0)]
        ctx.save(d0, recs[d0])
        stats["pages_read"] += 1
        print(f"  temperature=0 {'được hỗ trợ' if Temperature.supported else 'KHÔNG được hỗ trợ'}")
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(read_one, ctx, d, p): (d, p) for d, p in jobs[1:]}
            for n, f in enumerate(as_completed(futs), 1):
                d, p = futs[f]
                try:
                    r = f.result()
                except Exception as e:  # noqa: BLE001
                    stats["errors"] += 1
                    print(f"  ! {d} trang {p + 1}: {type(e).__name__}: {e}")
                    continue
                recs[d]["pages"] = [x for x in recs[d]["pages"] if x["page"] != p] + [r]
                ctx.save(d, recs[d])
                stats["pages_read"] += 1
                if n % 10 == 0:
                    print(f"  ... {n}/{len(jobs) - 1}")
    for doc_id, rec in recs.items():
        for pg in rec["pages"]:  # dựng lại text từ bản gốc (chuẩn hóa dòng thiếu "|"), rồi gắn header trang tiếp nối
            reprocess_page(ctx, doc_id, pg, stats)
        finalize_doc(ctx, doc_id, rec, stats)
        ctx.save(doc_id, rec)
    write_check_csv()
    stats.update(usage_totals(ctx.usage_log))
    return stats


def usage_totals(path: Path) -> dict:
    tot = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    if path.exists():
        for l in path.open(encoding="utf-8"):
            u = json.loads(l)
            tot["calls"] += 1
            for k in ("input_tokens", "output_tokens", "reasoning_tokens"):
                tot[k] += u.get(k) or 0
    return tot


def _all_pages() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(chunking_config()["paths"]["table_vlm_dir"].glob("*.json")):
        out += [(f.stem, p) for p in json.loads(f.read_text(encoding="utf-8"))["pages"]]
    return out


def write_check_csv() -> Path:
    dest = chunking_config()["paths"]["table_vlm_check"]
    rows = []
    for doc_id, p in _all_pages():
        c, u = p["check"], p["usage"]
        rows.append({"doc_id": doc_id, "page": p["page"] + 1, "match_rate": c["match_rate"], "ocr_recall": c.get("ocr_recall", c.get("recall_vs_ocr")),
                     "n_tokens_vlm": c["n_tokens_vlm"], "n_tokens_ocr": c["n_tokens_ocr"], "n_only_in_vlm": c["n_only_in_vlm"],
                     "spot_check": c["spot_check"], "only_in_vlm": " ".join(c["only_in_vlm"]), "n_tables": c["n_tables"],
                     "table_valid": c["table_valid"], "table_issue": c["table_issue"], "n_unknown": c["n_unknown"],
                     "continued_header": p.get("continued_header", False), "input_tokens": u["input_tokens"],
                     "output_tokens": u["output_tokens"], "reasoning_tokens": u["reasoning_tokens"], "finish_reason": u["finish_reason"],
                     "need_review": p["need_review"], "used_by_loader": not p["need_review"]})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["doc_id"])
        w.writeheader()
        w.writerows(rows)
    return dest


# ------------------------------------------------------------------------------------------------ spot check
def write_spot_check(n_random: int = 10, seed: int = 42) -> Path:
    """data/processed/table_vlm_spot_check.md: mọi trang spot_check=true + n_random trang ngẫu nhiên (seed) trong các trang còn lại."""
    cc = chunking_config()
    out_dir = cc["paths"]["out_dir"]
    img_dir = out_dir / "table_vlm_samples"
    img_dir.mkdir(parents=True, exist_ok=True)
    pages = _all_pages()
    spot = [(d, p) for d, p in pages if p["check"]["spot_check"]]
    rest = sorted(((d, p) for d, p in pages if not p["check"]["spot_check"]), key=lambda x: (x[0], x[1]["page"]))
    rnd = random.Random(seed).sample(rest, min(n_random, len(rest)))
    files = {}
    for pth in cc["paths"]["clean_dir"].glob("*.json"):
        if pth.name != "_manifest.json":
            d_ = json.loads(pth.read_text(encoding="utf-8"))
            files[Path(d_["file"]).stem] = d_["file"]
    md = ["# Spot check bảng VLM", "",
          f"- Trang spot_check=true (>= {SPOT_MIN_ONLY_VLM} số/mã chỉ có ở VLM, vẫn được dùng): {len(spot)}",
          f"- Trang ngẫu nhiên (seed={seed}, lấy từ các trang spot_check=false): {len(rnd)}", ""]
    for label, group in (("A. spot_check=true", spot), (f"B. ngẫu nhiên (seed={seed})", rnd)):
        md += [f"## {label}", ""]
        for doc_id, p in group:
            c = p["check"]
            img = img_dir / f"{doc_id}_p{p['page'] + 1}.png"
            if not img.exists():
                render_pdf_page(FILES_DIR / files[doc_id], p["page"], 100).save(img)
            only = c["only_in_vlm"]
            picked = [l for l in p["text_vlm_raw"].split("\n") if only and set(only) & tokens_of(l)]
            md += [f"### {doc_id} — trang {p['page'] + 1}", "",
                   f"- Ảnh: `{img.relative_to(ROOT).as_posix()}`",
                   f"- Tỉ lệ số trùng OCR cũ: {c['match_rate']}; số/mã chỉ có ở VLM ({c['n_only_in_vlm']}): {', '.join(only) if only else '(không có)'}",
                   f"- need_review: {p['need_review']}; continued_header: {p.get('continued_header', False)}", ""]
            if picked:
                md += ["```", *picked[:40], "```", ""]
    dest = out_dir / "table_vlm_spot_check.md"
    dest.write_text("\n".join(md), encoding="utf-8")
    return dest

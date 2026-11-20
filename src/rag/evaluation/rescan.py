"""Rà soát lại các trang OCR KHÔNG bị gắn cờ: chương trình tìm chỗ nghi ngờ theo luật, LLM đối chiếu với ẢNH GỐC rồi đề xuất sửa.

Lý do: kiểm mẫu (data/eval/sample_audit) cho thấy ~19% dòng của các trang không cờ có lỗi, phần lớn thuộc vài kiểu lặp lại.

Luật phát hiện (chương trình tìm, chỉ là GỢI Ý cho LLM; LLM và người duyệt mới quyết định):
  R1  dấu `?` (hoặc `%`, gạch nối dính chữ-số) nằm giữa câu/số, nơi đáng ra là -, =, +, ~, →, <, >...
  R2  dấu phẩy rồi tới chữ viết HOA (đầu dòng sau cũng tính): có thể là dấu chấm
  R3  chữ nằm trên vùng ĐỎ của ảnh (con dấu): đề xuất bỏ phần chữ đó
  R4  hai khối chữ cách xa nhau như hai ô bảng nhưng chưa có " | ": đề xuất thêm " | " giữa các ô
  R5  từ/cụm từ hiếm gặp trong toàn bộ kho văn bản nhưng gần giống (chỉ khác dấu) một từ/cụm thông dụng: nghi sai chữ/dấu
Rồi LLM so với ảnh gốc, trả các chỗ cần sửa theo đúng lược đồ của llm-review (ocr, anh, loai...) nên dùng lại được toàn bộ
dây chuyền: corrections-build → giao diện duyệt. Mọi thứ nằm ở lớp RIÊNG, không đụng data/interim/extract và lớp `corrected`
của 623 trang cờ:
  data/eval/llm_rescan/            kết quả LLM + gợi ý luật của từng trang
  data/interim/corrected_rescan/   lớp hiệu chỉnh (đã xây từ llm_rescan)
  data/eval/rescan_ui/             tiến độ giao diện duyệt

  python scripts/ingest.py --stage rescan-hints            # chỉ chạy luật (không tốn API): thống kê số gợi ý
  python scripts/ingest.py --stage rescan-eval             # luật bắt được bao nhiêu dòng sai trong 480 dòng kiểm mẫu
  python scripts/ingest.py --stage rescan-llm --dry-run    # đếm trang cần gọi LLM
  python scripts/ingest.py --stage rescan-llm --model gpt-5.4-mini --workers 4 --limit 10   # chạy thử
  python scripts/ingest.py --stage rescan-build            # dựng lớp hiệu chỉnh từ kết quả LLM
  python scripts/ingest.py --stage rescan-ui               # duyệt bằng giao diện corrections-ui
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from rag.config import EVAL_DIR, ROOT, load_config
from rag.evaluation.extract_eval import load_docs
from rag.evaluation.llm_review import locate, ocr_lines, page_key, parse_json, render_page
from rag.evaluation.sample_audit import eligible_pages, line_text
from rag.ingestion.vlm_ocr import model_ready

RESCAN_LLM_DIR = EVAL_DIR / "llm_rescan"
RESCAN_CORR_DIR = ROOT / "data" / "interim" / "corrected_rescan"
RESCAN_UI_DIR = EVAL_DIR / "rescan_ui"
RULE_NAMES = {"R1": "dau_hoi_giua_cau", "R2": "phay_roi_chu_hoa", "R3": "chu_tren_vung_do", "R4": "cot_bang_chua_tach",
              "R5": "tu_hiem_gan_giong_tu_thong_dung"}
MAX_HINTS_PER_PAGE = 30
UP = "A-ZÀ-ỸĐ"
LO = "a-zà-ỹđ"

PROMPT = """Bạn là người rà soát kết quả OCR của một trang tài liệu hành chính đại học (tiếng Việt).
Bạn được cho: (1) ẢNH của trang, (2) GỢI Ý do chương trình tìm ra (có thể sai), (3) VĂN BẢN OCR của trang.
ẢNH LÀ NGUỒN SỰ THẬT. Chỉ sửa khi bạn NHÌN THẤY trên ảnh rằng OCR sai. Không viết lại cả trang, không sửa chỗ đã đúng, không đoán chỗ không nhìn rõ.

Năm việc cần kiểm tra:
1. Dấu `?` (hoặc ký hiệu lạ) nằm giữa câu/số là OCR đọc nhầm một ký hiệu: nhìn ảnh để biết đúng là `-`, `–`, `=`, `+`, `~`, `→`, `<`, `>`, `≥`, `≤`, `/`... rồi sửa. Nếu không xác định được ký hiệu, ĐỪNG sửa. loai = "ky_hieu".
2. Sau dấu phẩy mà chữ kế tiếp viết HOA: xem ảnh, nếu đó thật ra là dấu chấm (hết câu) thì sửa `,` thành `.`; nếu ảnh đúng là dấu phẩy (liệt kê tên riêng, chức danh...) thì KHÔNG sửa. loai = "dau_cau".
3. Chữ do CON DẤU (nhất là dấu đỏ), chữ ký, logo, hình chìm tạo ra (thường là chữ rời rạc, vô nghĩa, kiểu "THÁNG LONG", "0 TRƯỜNG 0", "uc HIỆU TRƯỞNG R") thì đề xuất BỎ: "anh" = đoạn "ocr" sau khi bỏ phần chữ của dấu (rỗng "" nếu cả đoạn là chữ của dấu). Chỉ bỏ đúng phần chữ thuộc con dấu/chữ ký/logo; KHÔNG bỏ chữ thuộc nội dung văn bản (kể cả tiêu đề, chức danh người ký in sẵn như "HIỆU TRƯỞNG"). loai = "dau_do".
4. Bảng/cột: nếu một dòng là hàng của bảng mà các ô bị dính liền, chèn " | " giữa các ô (giữ nguyên chữ). "ocr" là cả đoạn dòng đó, "anh" là đúng đoạn đó nhưng có " | ". Nếu dòng vừa cần tách ô vừa sai chữ thì gộp thành MỘT mục. loai = "bang".
5. Từ sai chữ/dấu hoặc sai nghĩa/không hợp ngữ cảnh THẬT SỰ (ví dụ "Kế toản" → "Kế toán", "học phi" → "học phí"): đối chiếu ảnh rồi sửa. loai = "chu_dau" (sai chữ/dấu) hoặc "so_lieu" (tiền, ngày, giờ, mã, số điện thoại).

Quy tắc bắt buộc:
- "ocr" = đoạn NGẮN (khoảng 3-12 từ; dòng bảng có thể tới 25 từ) trích NGUYÊN VĂN từ VĂN BẢN OCR, đúng từng ký tự (kể cả " | "), để chương trình tìm lại được và đoạn đó chỉ xuất hiện MỘT lần trong trang (nếu lặp, lấy thêm từ bên cạnh).
- "anh" = đoạn đó sau khi sửa đúng theo ảnh. Không thêm lời bình.
- "quan_trong": true nếu là số liệu, tên riêng hoặc làm đổi nghĩa. "do_chac": cao, trung_binh hoặc thap.
- Mục GỢI Ý chỉ giúp bạn tìm; bạn được phép bỏ qua gợi ý sai và được phép báo thêm lỗi thật sự ngoài gợi ý.
- Không có chỗ nào cần sửa thì trả "co_loi": false và "loi": [].
Chỉ trả về MỘT đối tượng JSON, không thêm chữ nào khác:
{"co_loi": true, "loi": [{"ocr": "...", "anh": "...", "loai": "ky_hieu", "quan_trong": false, "do_chac": "cao"}]}
"""


# ------------------------------------------------------------------ dựng dòng và từ vựng
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", text.lower()))


class Vocab:
    """Tần suất âm tiết và cặp âm tiết trong TOÀN BỘ kho văn bản (kể cả trang có lớp chữ gốc, vốn rất chính xác)."""

    def __init__(self, docs: list[dict]):
        self.uni: Counter = Counter()
        self.bi: Counter = Counter()
        self.by_fold: dict[str, Counter] = {}
        for d in docs:
            for p in d["pages"]:
                if p.get("error"):
                    continue
                for line in p["derived"]["text"].split("\n"):
                    t = _tokens(line)
                    self.uni.update(t)
                    self.bi.update(zip(t, t[1:]))
        for w, c in self.uni.items():
            self.by_fold.setdefault(_fold(w), Counter())[w] = c

    def best_variant(self, w: str) -> str | None:
        v = self.by_fold.get(_fold(w))
        if not v:
            return None
        cand = [(c, x) for x, c in v.items() if x != w]
        return max(cand)[1] if cand else None


def lines_of(pg: dict) -> list[dict]:
    words = pg["raw"]["words"]
    if not words:
        return []
    med = sorted(max(1.0, w["box"][3] - w["box"][1]) for w in words)[len(words) // 2]
    out = []
    for ln in ocr_lines(words):
        out.append({"text": line_text(ln, med).strip(), "words": ln, "med": med})
    return out


# ------------------------------------------------------------------ các luật
RE_Q = re.compile(r"\?(?!\s*$)")                      # ? không nằm cuối dòng
RE_PCT = re.compile(r"(?<![\d)]) % (?=\S)")           # " % " đứng một mình giữa chữ (hay là dấu +)
RE_DASH_NUM = re.compile(rf"[{LO}]-\d")               # "tín chi-1.100.000" (có thể là dấu =)
RE_COMMA_UP = re.compile(rf",\s+[{UP}][{LO}]")        # ", Trưởng"


def r1_symbols(ln: dict) -> list[dict]:
    t, out = ln["text"], []
    for rx, why in ((RE_Q, "dấu ? giữa câu/số"), (RE_PCT, "dấu % đứng một mình (có thể là dấu +)"),
                    (RE_DASH_NUM, "gạch nối dính chữ và số (có thể là dấu =)")):
        for m in rx.finditer(t):
            a, b = max(0, m.start() - 25), min(len(t), m.end() + 25)
            out.append({"quy_tac": "R1", "text": t, "chi_tiet": f"{why}: «…{t[a:b]}…»"})
    return out[:2]


def r2_comma_upper(ln: dict, next_ln: dict | None) -> list[dict]:
    t, out = ln["text"], []
    for m in RE_COMMA_UP.finditer(t):
        a, b = max(0, m.start() - 20), min(len(t), m.end() + 20)
        out.append({"quy_tac": "R2", "text": t, "chi_tiet": f"sau dấu phẩy là chữ hoa: «…{t[a:b]}…»"})
    if next_ln and t.endswith(",") and re.match(rf"[{UP}][{LO}]", next_ln["text"]):
        out.append({"quy_tac": "R2", "text": t, "chi_tiet": f"dòng kết thúc bằng dấu phẩy, dòng sau bắt đầu bằng chữ hoa: «{next_ln['text'][:30]}…»"})
    return out[:2]


def red_ratio(img, box, pad: int = 2) -> float:
    """Tỷ lệ điểm ảnh có MỰC (không phải nền trắng) mà màu đỏ/hồng, trong khung chữ. Dùng để nhận ra dấu mộc đỏ."""
    import numpy as np
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    a = np.asarray(img.convert("RGB").crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad))).astype(int)
    if a.size == 0:
        return 0.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    ink = a.min(axis=2) < 200
    red = (r > 130) & (r - g > 50) & (r - b > 40)
    n = int(ink.sum())
    return float((red & ink).sum()) / n if n >= 30 else 0.0


def r3_red(ln: dict, img, thr: float = 0.5) -> list[dict]:
    if img is None:
        return []
    red = [w for w in ln["words"] if red_ratio(img, w["box"]) >= thr]
    if not red:
        return []
    names = " ".join(w["text"] for w in red)
    return [{"quy_tac": "R3", "text": ln["text"], "chi_tiet": f"{len(red)}/{len(ln['words'])} khối chữ nằm trên vùng ĐỎ: «{names}»"}]


def r4_columns(ln: dict, lo: float = 0.8, hi: float = 2.5) -> list[dict]:
    ws, med = ln["words"], ln["med"]
    gaps = [i for i in range(1, len(ws)) if lo * med < ws[i]["box"][0] - ws[i - 1]["box"][2] <= hi * med]
    if not gaps:
        return []
    parts, prev = [], 0
    for i in gaps:
        parts.append(" ".join(w["text"] for w in ws[prev:i]))
        prev = i
    parts.append(" ".join(w["text"] for w in ws[prev:]))
    return [{"quy_tac": "R4", "text": ln["text"], "chi_tiet": f"{len(gaps)} khoảng cách cột chưa có ' | '; đề xuất tách: «{' | '.join(parts)}»"}]


def r5_words(ln: dict, vocab: Vocab) -> list[dict]:
    toks = _tokens(ln["text"])
    out = []
    for i, w in enumerate(toks):
        if len(w) < 2:
            continue
        alt = vocab.best_variant(w)
        if not alt:
            continue
        cw, ca = vocab.uni[w], vocab.uni[alt]
        rare_word = cw <= 2 and ca >= 10 * max(1, cw) and ca >= 10
        rare_pair = False
        if i > 0 and ca > cw:
            rare_pair = vocab.bi[(toks[i - 1], w)] <= 1 and vocab.bi[(toks[i - 1], alt)] >= 5
        if rare_word or rare_pair:
            out.append({"quy_tac": "R5", "text": ln["text"],
                        "chi_tiet": f"«{w}» hiếm ({cw} lần) nhưng «{alt}» thông dụng ({ca} lần)" + (f"; cụm «{toks[i-1]} {w}» gần như chưa gặp" if rare_pair else "")})
    return out[:3]


def find_hints(pg: dict, vocab: Vocab, img=None) -> list[dict]:
    lines = lines_of(pg)
    base = pg["derived"]["text"]
    hints = []
    for k, ln in enumerate(lines):
        if len(ln["text"]) < 3 or ln["text"] not in base:  # dòng phải khớp đúng văn bản đã lưu
            continue
        found = r1_symbols(ln) + r2_comma_upper(ln, lines[k + 1] if k + 1 < len(lines) else None) + r3_red(ln, img) \
            + r4_columns(ln) + r5_words(ln, vocab)
        for h in found:
            h["dong"] = k + 1
            hints.append(h)
    order = {"R3": 0, "R1": 1, "R2": 2, "R4": 3, "R5": 4}
    hints.sort(key=lambda h: (order[h["quy_tac"]], h["dong"]))
    return hints


# ------------------------------------------------------------------ thống kê luật (không gọi API)
def run_hints(cfg: dict | None = None, limit: int | None = None, with_red: bool = True) -> dict:
    cfg = cfg or load_config("ocr")
    docs = load_docs(cfg)
    vocab = Vocab(docs)
    elig = eligible_pages(cfg)[: limit or None]
    dpi = cfg.get("render_dpi", 200)
    per_rule: Counter = Counter()
    pages_with: Counter = Counter()
    n_with = 0
    total = 0
    for d, p in elig:
        img = render_page(d, p, dpi) if with_red else None
        hs = find_hints(p, vocab, img)
        total += len(hs)
        n_with += bool(hs)
        per_rule.update(h["quy_tac"] for h in hs)
        pages_with.update({h["quy_tac"] for h in hs})
    return {"trang": len(elig), "trang_co_goi_y": n_with, "tong_goi_y": total,
            "goi_y_theo_luat": dict(per_rule), "trang_theo_luat": dict(pages_with)}


def eval_on_audit(cfg: dict | None = None, audit_dir: Path | None = None) -> dict:
    """Đối chiếu luật với kết quả kiểm mẫu của người: trong các dòng người bấm Reject, luật gắn cờ được bao nhiêu?
    Và trong các dòng người bấm Accept, luật gắn cờ nhầm bao nhiêu? (Chỉ để ĐO luật, không dùng để chỉnh luật cho khớp mẫu.)"""
    from rag.evaluation.sample_audit import AUDIT_DIR
    audit_dir = audit_dir or AUDIT_DIR
    cfg = cfg or load_config("ocr")
    sample = json.loads((audit_dir / "sample.json").read_text(encoding="utf-8"))
    st = json.loads((audit_dir / "state.json").read_text(encoding="utf-8"))["items"]
    vocab = Vocab(load_docs(cfg))
    idx = {(d["file"], p["page"]): (d, p) for d, p in eligible_pages(cfg)}
    dpi = cfg.get("render_dpi", 200)
    res = {"reject": Counter(), "accept": Counter()}
    for pg in sample["pages"]:
        got = idx.get((pg["file"], pg["page"]))
        if not got:
            continue
        d, p = got
        hs = find_hints(p, vocab, render_page(d, p, dpi))
        by_line: dict[str, set] = {}
        for h in hs:
            by_line.setdefault(h["text"], set()).add(h["quy_tac"])
        for it in pg["items"]:
            dec = st.get(it["item_id"], {}).get("d")
            if dec not in ("accept", "reject"):
                continue
            rules = by_line.get(it["text"].strip(), set())
            r = res["reject" if dec == "reject" else "accept"]
            r["dong"] += 1
            r["co_goi_y"] += bool(rules)
            for x in rules:
                r[x] += 1
    n_rej, n_acc = res["reject"]["dong"], res["accept"]["dong"]
    return {"dong_reject": n_rej, "reject_co_goi_y": res["reject"]["co_goi_y"],
            "ty_le_bat_duoc": round(res["reject"]["co_goi_y"] / n_rej, 3) if n_rej else None,
            "dong_accept": n_acc, "accept_bi_gan_co_nham": res["accept"]["co_goi_y"],
            "ty_le_gan_nham": round(res["accept"]["co_goi_y"] / n_acc, 3) if n_acc else None,
            "chi_tiet_reject": {k: v for k, v in res["reject"].items() if k.startswith("R")},
            "chi_tiet_accept": {k: v for k, v in res["accept"].items() if k.startswith("R")}}


# ------------------------------------------------------------------ LLM + đối chiếu
def _squash(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFC", s or "")).lower()


def check_item(it: dict, pg: dict, img, dpi: int) -> tuple[dict | None, str | None]:
    """Đối chiếu lại đề xuất của LLM bằng chương trình. Trả (mục đã chỉnh, None) hoặc (None, lý do loại).
    Mục đáng ngờ KHÔNG bị loại mà bị hạ độ chắc xuống 'thap' để giao diện duyệt xếp lên đầu và gắn cảnh báo."""
    ocr, anh = str(it.get("ocr", "")), str(it.get("anh", ""))
    if not ocr.strip():
        return None, "ocr_rong"
    if anh == ocr:
        return None, "khong_doi"
    loai = it.get("loai", "")
    base = pg["derived"]["text"]
    if base.count(ocr) == 0:
        return None, "ocr_khong_co_trong_van_ban"
    out = {**it, "vi_tri": locate(pg, ocr, dpi)}
    why = []
    if loai == "dau_do":
        if len(anh) >= len(ocr):  # bỏ chữ của dấu thì đoạn sau sửa phải NGẮN hơn đoạn gốc (có thể rỗng)
            why.append("dau_do_nhung_khong_bot_chu")
        box = (out["vi_tri"] or {}).get("box")
        if box and img is not None and red_ratio(img, box) < 0.10:
            why.append("vung_khong_do")
    elif loai in ("ky_hieu", "dau_cau", "chu_dau", "so_lieu"):
        if anh.strip() and fuzz.ratio(_squash(ocr), _squash(anh)) < 60:
            why.append("sua_qua_nhieu")
    elif loai == "bang" and _squash(ocr) != _squash(anh):
        why.append("bang_nhung_doi_ca_chu")
    if why:
        out["do_chac"] = "thap"
        out["doi_chieu"] = why
    return out, None


def run_rescan(cfg: dict | None = None, limit: int | None = None, dry_run: bool = False, out_dir: Path | None = None,
               caller=None, model_override: str | None = None, workers: int = 1) -> dict:
    cfg = cfg or load_config("ocr")
    vcfg = dict(cfg["vlm"])
    if model_override:
        if vcfg["provider"] == "openai":
            vcfg["openai"] = {**(vcfg.get("openai") or {}), "model": model_override}
        else:
            vcfg["model"] = model_override
    out_dir = out_dir or RESCAN_LLM_DIR
    prov, model, has_key, env_name, fn = model_ready(vcfg)
    dpi = cfg.get("render_dpi", 200)
    vocab = Vocab(load_docs(cfg))
    elig = eligible_pages(cfg)
    todo = [(d, p) for d, p in elig if not (out_dir / f"{page_key(d, p)}.json").exists()]  # đã có kết quả thì bỏ qua (chạy lại được)
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} trang cần LLM rà soát lại (mọi trang OCR không cờ, 98% đều có gợi ý từ luật). Nhà cung cấp: {prov} · mô hình: {model or '(CHƯA ĐIỀN)'} · "
          f"khóa {env_name}: {'có' if has_key else 'chưa có'}")
    print(f"Ước tính thô ~{len(todo) * 3000:,} token vào (ảnh ~1.750 + văn bản ~700 + gợi ý + lời dặn) và ~{len(todo) * 300:,} token ra.")
    if caller is None and (dry_run or not has_key or not model):
        print("Chỉ liệt kê, không gọi." if dry_run else
              ("Chưa điền vlm.<nhà cung cấp>.model (hoặc dùng --model)." if not model else f"Chưa có {env_name}."))
        return {"pages": len(todo), "called": 0}
    out_dir.mkdir(parents=True, exist_ok=True)
    caller = caller or fn
    prompt_sha = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def work(d: dict, p: dict) -> tuple[str, int, int, bool]:
        key = page_key(d, p)
        img = render_page(d, p, dpi)
        hints = find_hints(p, vocab, img)[:MAX_HINTS_PER_PAGE]
        hint_txt = "\n".join(f"- [{h['quy_tac']}] dòng {h['dong']}: {h['chi_tiet']}" for h in hints) or "(không có gợi ý)"
        prompt = PROMPT + "\nGỢI Ý TỪ CHƯƠNG TRÌNH:\n" + hint_txt + "\n\nVĂN BẢN OCR CỦA TRANG:\n" + p["derived"]["text"][:12000]
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp, usage = caller(img, vcfg, prompt)
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (attempt + 1) ** 2)
        else:
            raise last  # type: ignore[misc]
        parsed = parse_json(resp)
        kept, dropped = [], []
        for it in (parsed or {}).get("loi", []):
            if not (isinstance(it, dict) and it.get("ocr") and it.get("anh") is not None):
                continue
            ok, why = check_item(it, p, img, dpi)
            (kept if ok else dropped).append(ok or {**it, "ly_do_loai": why})
        rec = {"id": key, "file": d["file"], "page": p["page"], "route": p["route"], "provider": prov, "model": model,
               "prompt_sha256": prompt_sha, "generated_at": datetime.now().isoformat(timespec="seconds"), "usage": usage,
               "parse_ok": parsed is not None, "co_loi": bool(kept), "loi": kept, "loi_bi_loai": dropped,
               "goi_y_luat": [{k: h[k] for k in ("quy_tac", "dong", "chi_tiet")} for h in hints], "raw_response": resp,
               "note": "Đề xuất của mô hình sau khi chương trình đối chiếu; KHÔNG phải kết quả gốc, không ghi đè data/interim/extract."}
        (out_dir / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return key, len(kept), len(hints), parsed is not None

    called = errors = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(work, d, p): page_key(d, p) for d, p in todo}
        for n, f in enumerate(as_completed(futs), 1):
            key = futs[f]
            try:
                key, n_items, n_hints, ok = f.result()
                called += 1
                eta = (time.time() - t0) / n * (len(todo) - n)
                print(f"  [{n}/{len(todo)}] {key}: {n_hints} gợi ý → {n_items} chỗ đề xuất sửa" + ("" if ok else " (KHÔNG đọc được JSON)")
                      + f" · còn khoảng {eta / 60:.0f} phút", flush=True)
            except Exception as e:  # noqa: BLE001
                errors += 1
                print(f"  ! {key}: {type(e).__name__}: {e}", flush=True)
    print(f"Xong: gọi {called}, lỗi {errors}." + (" Chạy lại cùng lệnh để thử lại các trang lỗi." if errors else ""))
    return {"pages": len(todo), "called": called, "errors": errors}


def build_layer(cfg: dict | None = None, fresh: bool = False) -> dict:
    """Dựng lớp hiệu chỉnh riêng từ kết quả LLM rà soát lại. Cho phép mục chỉ đổi cấu trúc cột (thêm ' | ')."""
    from rag.ingestion.corrections import build
    return build(cfg, llm_dir=RESCAN_LLM_DIR, corr_dir=RESCAN_CORR_DIR, rules={"allow_structure_only": True}, fresh=fresh)


def repair_confirmed(cfg: dict | None = None, corr_dir: Path | None = None, dry_run: bool = False) -> dict:
    """Sửa hệ quả lỗi cũ của accept(): mục người đã bấm ĐÚNG nhưng bị đánh dấu `unapplicable` (không thay vào văn bản) dù đoạn gốc
    khớp đúng 1 lần. Chỉ dựa vào quyết định đã lưu (human_checked) và đề xuất LLM đã lưu; không tự sinh nội dung mới."""
    from rag.ingestion.corrections import _load, _refresh, _write
    cfg = cfg or load_config("ocr")
    corr_dir = corr_dir or RESCAN_CORR_DIR
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    st = {"da_sua": 0, "van_khong_ap_duoc": 0}
    for rec in _load(corr_dir).values():
        base = index[(rec["file"], rec["page"])]["derived"]["text"]
        changed = False
        for it in rec["items"]:
            if it["status"] != "unapplicable" or not it.get("human_checked"):
                continue
            if base.count(it["ocr"]) == 1 and it["anh_llm"] != it["ocr"]:
                it.update(status="human_applied", sua_thanh=it["anh_llm"], nguon="nguoi", llm_da_de_xuat=it["anh_llm"],
                          sua_chua="nguoi_bam_dung_nhung_chua_ap_dung")
                st["da_sua"] += 1
                changed = True
            else:
                st["van_khong_ap_duoc"] += 1
        if changed and not dry_run:
            _write(corr_dir, _refresh(rec, base))
    return st


def _occurrences(base: str, s: str) -> list[int]:
    out, i = [], base.find(s)
    while i >= 0:
        out.append(i)
        i = base.find(s, i + len(s))
    return out


def _is_word_edge(base: str, a: int, b: int) -> bool:
    """Đoạn base[a:b] không nằm lọt giữa một từ/số khác (tránh xóa/sửa '1' trong '2021')."""
    left = base[a - 1] if a > 0 else " "
    right = base[b] if b < len(base) else " "
    return not (left.isalnum() and base[a].isalnum()) and not (right.isalnum() and base[b - 1].isalnum())


def resolve_repeats(cfg: dict | None = None, corr_dir: Path | None = None, dry_run: bool = False) -> dict:
    """Mục người đã bấm ĐÚNG nhưng đoạn gốc lặp nhiều lần trong trang: xác định đúng lần xuất hiện NGƯỜI ĐÃ XEM.
    Giao diện duyệt hiện ảnh cắt tại `vi_tri` (khớp đầu tiên của locate) nên quyết định áp cho đúng lần đó; mục trùng hệt
    (cùng ocr, cùng anh) thì gán lần lượt các lần xuất hiện kế tiếp. Không chắc thì để nguyên, ghi lý do.
    Bỏ qua (không áp): đoạn ngắn <= 3 ký tự lặp lại, đoạn lọt giữa từ/số khác, chữ sửa đã có sẵn tại chỗ đó, vị trí không khớp."""
    from rag.evaluation.llm_review import _squash_map, _text_with_spans, _union
    from rag.ingestion.corrections import _load, _refresh, _write
    cfg = cfg or load_config("ocr")
    corr_dir = corr_dir or RESCAN_CORR_DIR
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    st: Counter = Counter()
    skipped = []
    for rec in _load(corr_dir).values():
        pg = index[(rec["file"], rec["page"])]
        base = pg["derived"]["text"]
        words = pg["raw"]["words"]
        text, spans = _text_with_spans(words) if words else ("", [])
        if text != base:
            st["bo_qua_trang_van_ban_khong_khop_khung"] += 1
            continue
        norm, idx = _squash_map(text)
        used: dict[str, set] = {}
        changed = False
        for it in rec["items"]:
            if it["status"] != "unapplicable" or not it.get("human_checked") or base.count(it["ocr"]) < 2:
                continue
            ocr, anh = it["ocr"], it["anh_llm"]
            occ = _occurrences(base, ocr)
            why = None
            sq, _ = _squash_map(ocr)
            pos = norm.find(sq.strip()) if sq.strip() else -1
            a0 = idx[pos] if pos >= 0 else -1
            if a0 not in occ:
                why = "vi_tri_hien_thi_khong_khop_lan_nao"
            elif len(ocr.strip()) <= 3:
                why = "doan_ngan_lap_lai"
            else:
                key = ocr + "\x00" + anh
                taken = used.setdefault(key, set())
                order = occ[occ.index(a0):] + occ[:occ.index(a0)]
                k = next((i for i in order if i not in taken), None)
                if k is None:
                    why = "het_lan_xuat_hien_de_gan"
                elif not _is_word_edge(base, k, k + len(ocr)):
                    why = "doan_lot_giua_tu_hoac_so"
                elif (anh and base[k:k + len(anh)] == anh) or (anh.startswith(ocr) and base[k + len(ocr):].startswith(anh[len(ocr):])):
                    why = "cho_sua_da_co_san"
                else:
                    taken.add(k)
                    it.update(status="human_applied", sua_thanh=anh, nguon="nguoi", llm_da_de_xuat=anh, lan_thu=occ.index(k),
                              sua_chua="lap_nhieu_lan_gan_theo_lan_nguoi_da_xem" if k == a0 else "lap_nhieu_lan_gan_theo_muc_trung_hech")
                    st["da_gan"] += 1
                    changed = True
            if why:
                st["khong_gan_" + why] += 1
                skipped.append({"item_id": it["item_id"], "loai": it["loai"], "so_lan": len(occ), "ocr": ocr[:50], "ly_do": why})
        if changed and not dry_run:
            _write(corr_dir, _refresh(rec, base))
    st["con_lai_khong_ap_duoc"] = sum(v for k, v in st.items() if k.startswith("khong_gan_"))
    return {"thong_ke": dict(st), "chua_gan": skipped}


def quality_after(cfg: dict | None = None, corr_dir: Path | None = None, audit_dir: Path | None = None) -> dict:
    """Đo lại bằng chính 480 dòng người đã chấm trong kiểm mẫu (trước khi rescan): xem văn bản SAU hiệu chỉnh thay đổi thế nào.
      - dòng Reject: còn nguyên (chưa sửa) / đã đổi; nếu người có gõ chữ đúng: giống hệt / gần hơn / xa hơn chữ đúng
      - dòng Accept: có bị đổi không (nếu đổi thì có thể là làm hỏng dòng đúng, hoặc người chấm bỏ sót; liệt kê để xem)
    Đây là đo trên chính mẫu đã dùng để phát hiện vấn đề, nên chỉ cho biết rescan có xử lý đúng các lỗi ĐÃ BIẾT hay không;
    tỷ lệ lỗi thật sự còn lại của cả 456 trang cần một mẫu mới (audit-build với hạt giống khác)."""
    from rag.evaluation.sample_audit import AUDIT_DIR
    from rag.ingestion.corrections import _load
    corr_dir, audit_dir = corr_dir or RESCAN_CORR_DIR, audit_dir or AUDIT_DIR
    cfg = cfg or load_config("ocr")
    sample = json.loads((audit_dir / "sample.json").read_text(encoding="utf-8"))
    st = json.loads((audit_dir / "state.json").read_text(encoding="utf-8"))["items"]
    layer = _load(corr_dir)
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}

    def key(s: str) -> str:
        return _squash(s)

    res = {"reject": Counter(), "accept": Counter()}
    changed_accept, no_map, worse, unfixed = [], 0, [], []
    for pg in sample["pages"]:
        pid = page_key({"file": pg["file"]}, {"page": pg["page"]})
        rec = layer.get(pid)
        base = index[(pg["file"], pg["page"])]["derived"]["text"].split("\n")
        if not rec:
            no_map += 1
            continue
        new = rec["corrected_text"].split("\n")
        if len(new) != len(base):
            no_map += 1
            continue
        for it in pg["items"]:
            dec = st.get(it["item_id"], {})
            d = dec.get("d")
            li = it["line_no"] - 1
            old_t, new_t = base[li], new[li]
            if old_t.strip() != it["text"].strip():
                no_map += 1
                continue
            changed = old_t != new_t
            r = res["reject" if d == "reject" else "accept"]
            r["dong"] += 1
            r["da_doi"] += changed
            if d == "reject":
                truth = (dec.get("dung") or "").strip()
                if truth and "không ghi" not in truth.lower() and "\n" not in truth:
                    r["co_chu_dung"] += 1
                    so, sn = fuzz.ratio(key(old_t), key(truth)), fuzz.ratio(key(new_t), key(truth))
                    r["giong_het_chu_dung"] += sn == 100
                    r["gan_hon_chua_giong_het"] += so < sn < 100
                    r["khong_doi_do_giong"] += sn == so and sn < 100
                    r["xa_hon"] += sn < so
                    if sn < so:
                        worse.append({"item_id": it["item_id"], "truoc": old_t, "sau": new_t, "chu_dung_nguoi_go": truth})
                elif not changed:
                    r["chua_sua_" + ("co_chu_dung" if truth else "khong_chu_dung")] += 0
                if not changed:
                    unfixed.append({"item_id": it["item_id"], "dong": old_t, "chu_dung_nguoi_go": truth})
            elif changed:
                changed_accept.append({"item_id": it["item_id"], "truoc": old_t, "sau": new_t})
    rj, ac = res["reject"], res["accept"]
    return {"dong_khong_doi_chieu_duoc": no_map,
            "dong_reject": dict(rj), "dong_accept": dict(ac),
            "ty_le_reject_da_duoc_sua": round(rj["da_doi"] / rj["dong"], 3) if rj["dong"] else None,
            "ty_le_accept_bi_doi": round(ac["da_doi"] / ac["dong"], 3) if ac["dong"] else None,
            "accept_bi_doi_chi_tiet": changed_accept, "reject_xa_chu_dung_hon": worse, "reject_chua_sua": unfixed}


def add_audit_leftovers(cfg: dict | None = None, corr_dir: Path | None = None, audit_dir: Path | None = None,
                        dry_run: bool = False) -> dict:
    """Đưa các dòng kiểm mẫu mà người đã Reject nhưng rescan CHƯA đổi chữ nào vào hàng chờ duyệt (giao diện rescan-ui).
    Ô "LLM sửa thành" được điền sẵn bằng chữ đúng CHÍNH BẠN đã gõ lúc kiểm mẫu (không có thì để nguyên chữ OCR, bạn tự gõ).
    Chỉ thêm mục mới (item_id `<trang>#a<n>`), không động vào mục đã có; chạy lại không thêm trùng."""
    from rag.evaluation.sample_audit import AUDIT_DIR
    from rag.ingestion.corrections import NUM_RE, _load, _now, _refresh, _write
    corr_dir, audit_dir = corr_dir or RESCAN_CORR_DIR, audit_dir or AUDIT_DIR
    cfg = cfg or load_config("ocr")
    dpi = cfg.get("render_dpi", 200)
    q = quality_after(cfg, corr_dir, audit_dir)
    sample = json.loads((audit_dir / "sample.json").read_text(encoding="utf-8"))
    where = {it["item_id"]: pg for pg in sample["pages"] for it in pg["items"]}
    layer = _load(corr_dir)
    index = {(d["file"], p["page"]): p for d in load_docs(cfg) for p in d["pages"] if not p.get("error")}
    st: Counter = Counter()
    for x in q["reject_chua_sua"]:
        pg = where[x["item_id"]]
        pid = page_key({"file": pg["file"]}, {"page": pg["page"]})
        rec = layer.get(pid)
        if not rec:
            st["trang_khong_co_trong_lop"] += 1
            continue
        page = index[(pg["file"], pg["page"])]
        base, ocr = page["derived"]["text"], x["dong"].strip()
        iid = f"{pid}#a{x['item_id'].split('#')[1]}"
        if any(it["item_id"] == iid for it in rec["items"]):
            st["da_co"] += 1
            continue
        if ocr == "" or base.count(ocr) != 1:
            st[f"bo_qua_doan_khop_{base.count(ocr) if ocr else 0}_lan"] += 1
            continue
        truth = x["chu_dung_nguoi_go"].strip()
        has = bool(truth) and "không ghi" not in truth.lower() and "\n" not in truth and truth != ocr
        st["co_chu_dung_san" if has else "chua_co_chu_dung"] += 1
        rec["items"].append({"item_id": iid, "ocr": ocr, "anh_llm": truth if has else ocr, "loai": "kiem_mau",
                             "quan_trong": bool(NUM_RE.findall(ocr)), "do_chac": "thap", "canh_bao": ["llm_chua_chac"],
                             "vi_tri": locate(page, ocr, dpi), "ly_do": "dong_kiem_mau_reject_chua_sua", "status": "pending_human",
                             "sua_thanh": "", "nguon": None, "model": "chu_dung_nguoi_go_luc_kiem_mau", "at": _now()})
        if not dry_run:
            _write(corr_dir, _refresh(rec, base))
        st["da_them"] += 1
    return dict(st)

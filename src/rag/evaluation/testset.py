"""Lõi bộ câu hỏi đánh giá: schema, đọc/ghi questions.jsonl, định vị quote trong văn bản tài liệu, độ trùng từ, chia dev/test.

Văn bản tài liệu = data/processed/docs/<doc_id>.txt (văn bản đã nối trang; đây là gốc tọa độ char_start/char_end của chunk).
Không gọi mạng. Mọi hàm ở đây kiểm thử được độc lập (tests/test_testset_core.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from rag.config import ROOT, load_config

DOCS_DIR = ROOT / "data" / "processed" / "docs"
TYPES = ("factoid", "dieu_kien", "thu_tuc", "tra_bang", "nhieu_doan", "khau_ngu")
BEHAVIORS = ("answer", "refuse", "ask_clarify_or_multi_version")
STATUSES = ("pending", "accepted", "edited", "rejected", "unsure")   # unsure = "Không chắc" (chưa tính vào bộ chấm)
SCORED = ("accepted", "edited")
OOS_KINDS = ("khong_lien_quan", "cung_linh_vuc", "ca_nhan", "de_nham")


def testset_config() -> dict:
    cfg = load_config("testset")
    cfg["paths"] = {k: ROOT / v for k, v in cfg["paths"].items()}
    return cfg


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ văn bản tài liệu
_doc_cache: dict[tuple[str, str], str] = {}


def load_doc_text(doc_id: str, docs_dir: Path | None = None) -> str:
    """Đọc đúng văn bản gốc tọa độ (không chuẩn hóa, giữ nguyên ký tự để char_start/char_end khớp chunk)."""
    d = Path(docs_dir or DOCS_DIR)
    key = (str(d), doc_id)
    if key not in _doc_cache:
        _doc_cache[key] = (d / f"{doc_id}.txt").read_text(encoding="utf-8")
    return _doc_cache[key]


def doc_sha(doc_id: str, docs_dir: Path | None = None) -> str:
    return sha256_text(load_doc_text(doc_id, docs_dir))


def clear_doc_cache() -> None:
    _doc_cache.clear()


# ------------------------------------------------------------------ chuẩn hóa + định vị quote
def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """NFC + gộp mọi chuỗi khoảng trắng thành 1 dấu cách. Trả (chuỗi chuẩn hóa, map: vị trí chuẩn hóa -> vị trí trong text gốc).

    Văn bản tài liệu đã ở dạng NFC (kiểm bằng test) nên NFC từng ký tự không đổi độ dài; nếu gặp ký tự đổi độ dài thì
    vẫn lập map theo ký tự gốc đầu tiên của cụm."""
    out: list[str] = []
    mp: list[int] = []
    prev_space = True  # bỏ khoảng trắng đầu
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                mp.append(i)
                prev_space = True
            continue
        n = unicodedata.normalize("NFC", ch)
        for c in n:
            out.append(c)
            mp.append(i)
        prev_space = False
    if out and out[-1] == " ":
        out.pop()
        mp.pop()
    return "".join(out), mp


def norm_text(s: str) -> str:
    return _norm_with_map(s)[0]


def locate_quote(text: str, quote: str, window: tuple[int, int] | None = None, fuzzy_min: float = 0.9) -> dict:
    """Tìm `quote` trong `text` (văn bản tài liệu).

    Trả {"method": "exact"|"fuzzy"|"none", "char_start", "char_end", "score"}; char_* là tọa độ trong `text` GỐC.
    Khớp chính xác sau chuẩn hóa NFC + khoảng trắng; có nhiều chỗ khớp thì ưu tiên chỗ nằm trong `window` (đơn vị sinh), rồi chỗ đầu tiên.
    Không khớp: khớp mờ (rapidfuzz partial alignment) với điểm >= fuzzy_min. Không được: method "none".
    """
    q = norm_text(quote)
    none = {"method": "none", "char_start": None, "char_end": None, "score": 0.0}
    if not q:
        return none
    tn, mp = _norm_with_map(text)
    hits: list[int] = []
    i = tn.find(q)
    while i != -1 and len(hits) < 200:
        hits.append(i)
        i = tn.find(q, i + 1)

    def to_span(a: int, b: int) -> tuple[int, int]:
        s = mp[a]
        e = mp[b - 1] + 1  # b là cận trên (không gồm) trong chuỗi chuẩn hóa
        return s, e

    if hits:
        pick = hits[0]
        if window is not None:
            inside = [h for h in hits if window[0] <= mp[h] and mp[h + len(q) - 1] < window[1]]
            if inside:
                pick = inside[0]
        s, e = to_span(pick, pick + len(q))
        return {"method": "exact", "char_start": s, "char_end": e, "score": 1.0}
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover
        return none
    best = None
    if window is not None:  # ưu tiên tìm trong đơn vị sinh (nhanh và đúng chỗ)
        lo = max(0, bisect_left_map(mp, window[0]))
        hi = bisect_left_map(mp, window[1] + 1)
        sub = tn[lo:hi]
        if len(sub) >= len(q) * 0.5:
            al = fuzz.partial_ratio_alignment(q, sub)
            if al is not None:
                best = (al.score / 100.0, lo + al.dest_start, lo + al.dest_end)
    if best is None or best[0] < fuzzy_min:
        al = fuzz.partial_ratio_alignment(q, tn)
        if al is not None and (best is None or al.score / 100.0 > best[0]):
            best = (al.score / 100.0, al.dest_start, al.dest_end)
    # khớp mờ KHÔNG được làm đổi số (24 ≠ 25): đáp án là con số thì quote sai số = quote bịa
    if best and best[0] >= fuzzy_min and best[2] > best[1] and re.findall(r"\d+", q) == re.findall(r"\d+", tn[best[1]:best[2]]):
        s, e = to_span(best[1], best[2])
        return {"method": "fuzzy", "char_start": s, "char_end": e, "score": round(best[0], 4)}
    return none


def bisect_left_map(mp: list[int], pos: int) -> int:
    import bisect
    return bisect.bisect_left(mp, pos)


# ------------------------------------------------------------------ độ trùng từ
_STOP: frozenset[str] | None = None
_PUNCT = re.compile(r"[^\w\s]|_", re.U)


def _stopwords() -> frozenset[str]:
    global _STOP
    if _STOP is None:
        p = ROOT / "configs" / "stopwords_vi.txt"
        words: set[str] = set()
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    words.add(line)
        _STOP = frozenset(words)
    return _STOP


def word_tokens(text: str) -> list[str]:
    """Tách từ tiếng Việt bằng pyvi (từ ghép nối bằng '_'); không có pyvi thì tách theo khoảng trắng. Chữ thường, bỏ dấu câu."""
    t = nfc(text).lower()
    try:
        from pyvi import ViTokenizer
        t = ViTokenizer.tokenize(t)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for w in t.split():
        w = re.sub(r"^[^\w]+|[^\w]+$", "", w).strip("_")
        if w:
            out.append(w)
    return out


def lexical_overlap(question: str, span_texts: list[str], drop_stop: bool = True) -> float:
    """Tỉ lệ token (sau tách từ pyvi) của câu hỏi có trong các span. drop_stop=True bỏ từ dừng (đo từ nội dung)."""
    qt = word_tokens(question)
    if drop_stop:
        sw = _stopwords()
        qt = [t for t in qt if t not in sw and t.replace("_", " ") not in sw]
    if not qt:
        return 0.0
    st: set[str] = set()
    for s in span_texts:
        toks = word_tokens(s)
        st.update(toks)
        for t in toks:  # từ ghép cũng khớp theo từng âm tiết (câu hỏi hay tách cụm khác văn bản)
            if "_" in t:
                st.update(t.split("_"))
    hit = 0
    for t in qt:
        if t in st or (("_" in t) and all(p in st for p in t.split("_"))):
            hit += 1
    return round(hit / len(qt), 4)


def _plain_words(s: str) -> list[str]:
    return [w for w in re.sub(r"[^\w\s]", " ", nfc(s).lower()).split() if w]


def max_copied_run(question: str, span_texts: list[str]) -> int:
    """Độ dài (số từ) của cụm từ liên tiếp DÀI NHẤT mà câu hỏi chép nguyên từ span."""
    q = _plain_words(question)
    best = 0
    for s in span_texts:
        w = _plain_words(s)
        if not q or not w:
            continue
        prev = [0] * (len(w) + 1)
        for i in range(1, len(q) + 1):
            cur = [0] * (len(w) + 1)
            qi = q[i - 1]
            for j in range(1, len(w) + 1):
                if qi == w[j - 1]:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best:
                        best = cur[j]
            prev = cur
    return best


def is_duplicate(q: str, others: list[str], ratio: int = 90) -> str | None:
    """Câu trùng (rapidfuzz token_sort_ratio >= ratio) với một câu trong others thì trả câu đó."""
    from rapidfuzz import fuzz
    a = " ".join(_plain_words(q))
    for o in others:
        if fuzz.token_sort_ratio(a, " ".join(_plain_words(o))) >= ratio:
            return o
    return None


# ------------------------------------------------------------------ phủ span
def span_coverage(chunk: tuple[int, int], span: tuple[int, int]) -> float:
    """Ký tự giao nhau / độ dài span (cùng doc_id do người gọi kiểm)."""
    (cs, ce), (ss, se) = chunk, span
    if se <= ss or cs is None or ce is None:
        return 0.0
    inter = max(0, min(ce, se) - max(cs, ss))
    return inter / (se - ss)


def union_coverage(intervals: list[tuple[int, int]], span: tuple[int, int]) -> float:
    """Phần span được phủ bởi HỢP các đoạn (cùng doc)."""
    ss, se = span
    if se <= ss:
        return 0.0
    cl = sorted((max(a, ss), min(b, se)) for a, b in intervals if a is not None and b is not None and min(b, se) > max(a, ss))
    tot, cur_s, cur_e = 0, None, None
    for a, b in cl:
        if cur_e is None or a > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = a, b
        else:
            cur_e = max(cur_e, b)
    if cur_e is not None:
        tot += cur_e - cur_s
    return tot / (se - ss)


# ------------------------------------------------------------------ đọc/ghi questions.jsonl
def load_questions(path: Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_questions(rows: list[dict], path: Path, keep_bak: int = 30) -> None:
    """Ghi atomic (file tạm rồi os.replace) sau khi sao lưu bản cũ thành .bak có timestamp (giữ `keep_bak` bản mới nhất)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.stat().st_size > 0:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (p.parent / f"{p.name}.{stamp}.bak").write_bytes(p.read_bytes())
        baks = sorted(p.parent.glob(p.name + ".*.bak"))
        for old in baks[:-keep_bak]:
            old.unlink(missing_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, p)


def append_log(path: Path, rec: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def new_question(**kw) -> dict:
    """Bản ghi câu hỏi theo schema (mục 4); trường không truyền lấy mặc định."""
    q = {"id": "", "question": "", "user_ctx": {}, "in_scope": True, "expected_behavior": "answer", "type": "factoid", "doc_type": "",
         "expected": [], "answer_ref": "", "version_note": "", "lexical_overlap": None, "split": "", "created_by": "llm",
         "gen": {"model": "", "prompt_sha256": "", "unit": ""},
         "review": {"status": "pending", "reviewer": "", "time": "", "note": ""}}
    q.update(kw)
    return q


def next_id(rows: list[dict], prefix: str = "q") -> str:
    n = 0
    for r in rows:
        m = re.fullmatch(rf"{re.escape(prefix)}(\d+)", r.get("id", ""))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:04d}"


def span_texts(q: dict, docs_dir: Path | None = None) -> list[str]:
    out = []
    for e in q.get("expected") or []:
        try:
            out.append(load_doc_text(e["doc_id"], docs_dir)[e["char_start"]:e["char_end"]])
        except (OSError, KeyError, TypeError):
            out.append(e.get("quote", ""))
    return out


def recompute_overlap(q: dict, docs_dir: Path | None = None) -> float | None:
    if not q.get("expected"):
        return None
    return lexical_overlap(q["question"], span_texts(q, docs_dir))


def fix_span(e: dict, docs_dir: Path | None = None) -> dict:
    """Gán lại quote = đúng đoạn văn bản tại [char_start, char_end) (bỏ khoảng trắng đầu/cuối, cập nhật tọa độ tương ứng)."""
    t = load_doc_text(e["doc_id"], docs_dir)
    s, en = int(e["char_start"]), int(e["char_end"])
    s, en = max(0, min(s, len(t))), max(0, min(en, len(t)))
    while s < en and t[s].isspace():
        s += 1
    while en > s and t[en - 1].isspace():
        en -= 1
    return {**e, "char_start": s, "char_end": en, "quote": t[s:en], "doc_sha256": sha256_text(t)[:16]}


# ------------------------------------------------------------------ chia dev/test
def assign_splits(rows: list[dict], seed: int = 42, dev_frac: float = 0.3, statuses=SCORED) -> dict[str, int]:
    """Gán split cho các câu accepted/edited CHƯA có split, phân tầng theo (type, doc_type), ổn định theo seed.

    Câu đã có split được GIỮ NGUYÊN (đã chạy tham số trên dev thì không đổi tập). Mỗi tầng: số dev mục tiêu = làm tròn dev_frac*n,
    trừ đi số dev đã có; phần dư làm tròn được dồn sang tầng sau (carry) để tổng gần đúng 30%. Trả {split: số câu mới gán}.
    """
    strata: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r["review"]["status"] in statuses:
            strata.setdefault((r["type"], r["doc_type"]), []).append(r)
    added = {"dev": 0, "test": 0}
    carry = 0.0
    for key in sorted(strata):
        grp = sorted(strata[key], key=lambda r: r["id"])
        have_dev = sum(1 for r in grp if r.get("split") == "dev")
        new = [r for r in grp if not r.get("split")]
        if not new:
            continue
        want_total = dev_frac * len(grp) + carry
        want_dev = max(0, int(round(want_total)))
        carry = want_total - want_dev
        n_dev = max(0, min(len(new), want_dev - have_dev))
        rng = random.Random(f"{seed}|{key[0]}|{key[1]}")
        order = list(new)
        rng.shuffle(order)
        for i, r in enumerate(order):
            r["split"] = "dev" if i < n_dev else "test"
            added[r["split"]] += 1
    return added


# ------------------------------------------------------------------ gộp kết quả của nhiều người duyệt
def merge_reviews(base: list[dict], others: list[list[dict]]) -> tuple[list[dict], dict]:
    """Gộp các bản questions.jsonl do nhiều người duyệt (mỗi người một hàng đợi riêng) vào `base`.

    Mỗi id: lấy bản đã duyệt (status != pending) có review.time MỚI NHẤT; chưa ai duyệt thì giữ bản của base. Câu mới (id chưa có trong base,
    thường là câu người viết thêm) được thêm vào. Trả (danh sách đã gộp theo thứ tự base rồi câu mới, thống kê)."""
    by_id = {q["id"]: q for q in base}
    order = [q["id"] for q in base]
    st = {"updated": 0, "added": 0, "conflicts": 0}
    for rows in others:
        for q in rows:
            cur = by_id.get(q["id"])
            if cur is None:
                by_id[q["id"]] = q
                order.append(q["id"])
                st["added"] += 1
                continue
            a, b = cur["review"], q["review"]
            if b["status"] == "pending":
                continue
            if a["status"] != "pending" and a.get("time") and b.get("time") and a["time"] != b["time"] and a.get("reviewer") != b.get("reviewer"):
                st["conflicts"] += 1
            if a["status"] == "pending" or (b.get("time") or "") > (a.get("time") or ""):
                by_id[q["id"]] = q
                st["updated"] += 1
    return [by_id[i] for i in order], st

"""Sửa các lỗi nhận dạng / bố cục sau OCR (chữ của 71 file scan), không đụng vào dữ liệu gốc.

Các lỗi được sửa (mỗi quy tắc đều bảo thủ: không chắc thì để nguyên):
    bullet   Ký hiệu danh sách bị đọc thành chữ: dòng bắt đầu bằng 's', '°', 'ø', '¢', '»' ... rồi tới chữ / số
             -> thay bằng '- '.
    merged   Từ tiếng Việt bị dính (mất khoảng trắng): 'Hệthốngthôngtinkếtoán' -> 'Hệ thống thông tin kế toán'.
             Tách bằng từ vựng chuẩn (Viterbi). Chỉ áp dụng cho từ CÓ DẤU tiếng Việt, không nằm trong dòng
             chứa địa chỉ web / email, và chỉ khi mọi mảnh đều là âm tiết có trong từ vựng.
    known    Nhầm cặp ký tự đã biết: 'E-Leaming' -> 'E-Learning' (danh sách nhỏ, viết tay).

KHÔNG sửa (có chủ ý):
    - chuỗi chữ đơn liên tiếp (X X X, R R R): là dấu trong ma trận đối chiếu hoặc nhiễu đường kẻ bảng, không phải từ bị tách;
    - từ tiếng Anh dài (professional, Introduction): là từ hợp lệ;
    - thứ tự đọc sai ở bảng: cần tọa độ từng từ, làm ở bước riêng.

Từ vựng chuẩn lấy từ nguồn KHÔNG qua OCR: chữ PDF có lớp chữ + nội dung website + tên môn học trên website.

Chạy:
    python fix_ocr.py validate     # kiểm chứng thuật toán tách từ trên chữ chuẩn
    python fix_ocr.py run          # sửa -> extract/text_fixed/ + fix_changes.csv + fix_log.csv
    python fix_ocr.py apply        # sao lưu extract/text/ (file OCR) sang text_ocr_raw/ rồi thay bằng bản đã sửa
    python fix_ocr.py revert       # khôi phục bản gốc từ text_ocr_raw/
"""
import argparse
import collections
import csv
import json
import math
import random
import re
import shutil
import sys
import unicodedata

import extract_files as ef

VN_LETTER = re.compile("[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)
BULLET = re.compile(r"^(\s*)([s°ø¢»®©])\s+(?=\w)")
KNOWN = {"E-Leaming": "E-Learning", "Leaming": "Learning", "leaming": "learning"}
URL_CONTEXT = re.compile(r"https?://|www\.|@", re.I)
RUN = re.compile(r"[^\W\d_]{8,}")
MAX_PIECE = 8
PIECE_PENALTY = 2.0
CHANGE_FIELDS = ["file_key", "line", "rule", "before", "after"]
LOG_FIELDS = ["file_key", "lines", "bullet", "merged", "known", "digit", "code"]
DIGIT_FIX = str.maketrans({"l": "1", "I": "1", "O": "0"})
DIGIT_TOKEN = re.compile(r"(?<![\w.])(?=[0-9lIO]{2,3}(?!\w))(?=[0-9lIO]*\d)(?=[0-9lIO]*[lIO])[0-9lIO]{2,3}(?!\w)")
CODE_TOKEN = re.compile(r"\b([A-Z]{3})([0-9IlO]{4})\b")
_CODES: set = set()


def fixed_dir():
    return ef.EXT / "text_fixed"


def backup_dir():
    return ef.EXT / "text_ocr_raw"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def words(s):
    return re.findall(r"[^\W\d_]+", nfc(s).lower())


# ----------------------------------------------------------------------------- từ vựng chuẩn
def build_vocab():
    """Đếm âm tiết trong chữ KHÔNG qua OCR. Trả về (vocab, đếm theo file, đếm nguồn website)."""
    ex = {r["file_key"]: r for r in ef.read_extract_log()}
    per = {}
    for k, r in ex.items():
        if r["method"] == "pdf_text" and r["status"] == "ok":
            per[k] = collections.Counter(words((ef.TEXT / f"{k}.txt").read_text(encoding="utf-8")))
    recs = json.loads(ef.SRC.read_text(encoding="utf-8"))
    base = collections.Counter(words("\n".join(r["title"] + "\n" + r["content"] for r in recs)))
    base.update(words(" ".join(s for r in recs for c in (r.get("curriculum") or []) for s in c["subjects"])))
    vocab = collections.Counter(base)
    for c in per.values():
        vocab.update(c)
    return vocab, per, base


def valid_codes():
    """Mã học phần (3 chữ + 4 số) đã được đọc ĐÚNG ở nơi khác trong dữ liệu (mọi file text + nội dung website).
    Một mã bị OCR đọc sai chỉ được sửa khi mã sau sửa trùng một mã trong tập này."""
    if not _CODES:
        rx = re.compile(r"\b[A-Z]{3}\d{4}\b")
        for p in ef.TEXT.glob("*.txt"):
            _CODES.update(rx.findall(p.read_text(encoding="utf-8")))
        for r in json.loads(ef.SRC.read_text(encoding="utf-8")):
            _CODES.update(rx.findall(r["content"]))
    return _CODES


# ----------------------------------------------------------------------------- tách từ dính
def is_syllable(w):
    """Âm tiết tiếng Việt hợp lệ ở mức tối thiểu: ≥ 2 chữ cái và đúng MỘT cụm nguyên âm.
    Loại từ dính trong từ vựng (vd 'hànội' có 2 cụm), chữ viết tắt không nguyên âm (vd 'cđr') và mảnh 1 chữ cái."""
    if len(w) < 2:
        return False
    base = unicodedata.normalize("NFD", w.replace("đ", "d"))
    base = "".join(c for c in base if not unicodedata.combining(c))
    return len(re.findall(r"[aeiouy]+", base)) == 1


def segment(tok, vocab, min_count=2):
    """Tách chuỗi dính thành các âm tiết có trong từ vựng (Viterbi, ưu tiên ít mảnh).
    Trả về danh sách mảnh (giữ nguyên chữ hoa / thường của tok) hoặc None nếu không tách trọn vẹn được."""
    t = tok.lower()
    n = len(t)
    total = sum(vocab.values())
    inf = 1e18
    best, back = [inf] * (n + 1), [0] * (n + 1)
    best[0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(0, i - MAX_PIECE), i):
            w = t[j:i]
            c = vocab.get(w, 0)
            if c >= min_count and is_syllable(w) and best[j] < inf:
                cost = best[j] - math.log(c / total) + PIECE_PENALTY
                if cost < best[i]:
                    best[i], back[i] = cost, j
    if best[n] >= inf:
        return None
    cuts, i = [], n
    while i > 0:
        cuts.append(back[i])
        i = back[i]
    cuts = sorted(set(cuts) - {0})
    out, prev = [], 0
    for c in cuts + [n]:
        out.append(tok[prev:c])
        prev = c
    return out


def split_merged_token(tok, vocab):
    """Chỉ tách từ có dấu tiếng Việt, chưa có trong từ vựng, và tách ra ≥ 2 mảnh hợp lệ."""
    if tok.lower() in vocab or not VN_LETTER.search(tok):
        return None
    r = segment(tok, vocab)
    return r if r and len(r) >= 2 else None


# ----------------------------------------------------------------------------- sửa một dòng
def fix_line(line, vocab):
    """Trả về (dòng mới, danh sách (quy tắc, trước, sau))."""
    events = []
    cur = nfc(line)
    m = BULLET.match(cur)
    if m:
        new = m.group(1) + "- " + cur[m.end():]
        events.append(("bullet", cur, new))
        cur = new
    if not URL_CONTEXT.search(cur):
        def repl(mm):
            r = split_merged_token(mm.group(0), vocab)
            return " ".join(r) if r else mm.group(0)
        new = RUN.sub(repl, cur)
        if new != cur:
            events.append(("merged", cur, new))
            cur = new
    if not URL_CONTEXT.search(cur):
        new = DIGIT_TOKEN.sub(lambda mm: mm.group(0).translate(DIGIT_FIX), cur)
        if new != cur:
            events.append(("digit", cur, new))
            cur = new

        def code(mm):
            fixed = mm.group(1) + mm.group(2).translate(DIGIT_FIX)
            return fixed if fixed != mm.group(0) and fixed in valid_codes() else mm.group(0)
        new = CODE_TOKEN.sub(code, cur)
        if new != cur:
            events.append(("code", cur, new))
            cur = new
    for bad, good in KNOWN.items():
        new = re.sub(r"(?<!\w)" + re.escape(bad) + r"(?!\w)", good, cur)
        if new != cur:
            events.append(("known", cur, new))
            cur = new
    return cur, events


# ----------------------------------------------------------------------------- chạy
def ocr_file_keys():
    return sorted(r["file_key"] for r in ef.read_extract_log() if r["method"] == "pdf_ocr" and r["status"] == "ok")


def run(verbose=True):
    vocab, _, _ = build_vocab()
    fixed_dir().mkdir(parents=True, exist_ok=True)
    changes, log = [], []
    for k in ocr_file_keys():
        src = backup_dir() / f"{k}.txt"
        if not src.exists():
            src = ef.TEXT / f"{k}.txt"       # chưa apply lần nào thì đọc từ text/
        lines = src.read_text(encoding="utf-8").split("\n")
        out, cnt = [], collections.Counter()
        for i, l in enumerate(lines, 1):
            new, events = fix_line(l, vocab)
            out.append(new)
            for rule, before, after in events:
                cnt[rule] += 1
                changes.append({"file_key": k, "line": i, "rule": rule, "before": before[:160], "after": after[:160]})
        (fixed_dir() / f"{k}.txt").write_text("\n".join(out), encoding="utf-8")
        log.append({"file_key": k, "lines": len(lines), "bullet": cnt["bullet"], "merged": cnt["merged"], "known": cnt["known"],
                    "digit": cnt["digit"], "code": cnt["code"]})
    ef._write_csv(ef.EXT / "fix_changes.csv", changes, CHANGE_FIELDS)
    ef._write_csv(ef.EXT / "fix_log.csv", log, LOG_FIELDS)
    if verbose:
        tot = collections.Counter()
        for r in log:
            for k in ("bullet", "merged", "known", "digit", "code"):
                tot[k] += r[k]
        print(f"Đã xử lý {len(log)} file -> {fixed_dir()}")
        print(f"Số dòng đã sửa theo quy tắc: {dict(tot)} | chi tiết từng thay đổi: {ef.EXT / 'fix_changes.csv'}")
    return changes, log


def apply():
    """Sao lưu chữ OCR gốc (một lần) rồi thay bằng bản đã sửa. Dùng revert() để quay lại."""
    backup_dir().mkdir(parents=True, exist_ok=True)
    n = 0
    for k in ocr_file_keys():
        fx = fixed_dir() / f"{k}.txt"
        if not fx.exists():
            continue
        bk = backup_dir() / f"{k}.txt"
        if not bk.exists():
            shutil.copy2(ef.TEXT / f"{k}.txt", bk)
        shutil.copy2(fx, ef.TEXT / f"{k}.txt")
        n += 1
    return n


def revert():
    n = 0
    for p in sorted(backup_dir().glob("*.txt")) if backup_dir().exists() else []:
        shutil.copy2(p, ef.TEXT / p.name)
        n += 1
    return n


# ----------------------------------------------------------------------------- kiểm chứng
def validate(n_files=20, lines_per_file=12, seed=3):
    """Lấy cụm từ thật trong chữ chuẩn, tự dính lại rồi tách bằng thuật toán, với từ vựng đã LOẠI file chứa cụm đó.
    Chỉ thử các cụm mà quy tắc thật sẽ áp dụng (có dấu tiếng Việt, toàn chữ cái). Đây là số đo độ đúng của thuật toán,
    không phải của chữ OCR."""
    vocab, per, _ = build_vocab()
    random.seed(seed)
    ok = bad = none = 0
    bad_ex = []
    for k in random.sample(sorted(per), min(n_files, len(per))):
        vc = vocab.copy()
        vc.subtract(per[k])
        vc = +vc
        lines = [l for l in (ef.TEXT / f"{k}.txt").read_text(encoding="utf-8").split("\n") if 25 < len(l) < 120]
        for l in random.sample(lines, min(lines_per_file, len(lines))):
            ws = re.findall(r"[^\W\d_]+", nfc(l))
            if len(ws) < 4:
                continue
            i = random.randrange(0, len(ws) - 3)
            ph = ws[i:i + random.choice([3, 4])]
            merged = "".join(ph)
            if len(merged) < 8 or not VN_LETTER.search(merged) or any(w.lower() not in vc for w in ph):
                continue
            r = split_merged_token(merged, vc) if merged.lower() not in vc else None
            if r is None:
                none += 1
            elif [x.lower() for x in r] == [x.lower() for x in ph]:
                ok += 1
            else:
                bad += 1
                bad_ex.append((ph, r))
    tot = ok + bad + none
    return {"tong": tot, "dung": ok, "sai": bad, "khong_tach_duoc": none, "vi_du_sai": bad_ex[:6]}


def main():
    ap = argparse.ArgumentParser(description="Sửa lỗi nhận dạng / bố cục sau OCR")
    ap.add_argument("cmd", choices=["validate", "run", "apply", "revert"])
    a = ap.parse_args()
    if a.cmd == "validate":
        v = validate()
        t = max(v["tong"], 1)
        print(f"Kiểm chứng tách từ dính trên chữ chuẩn: {v['tong']} cụm")
        print(f"   tách đúng hoàn toàn : {v['dung']} ({100 * v['dung'] / t:.0f}%)")
        print(f"   tách SAI            : {v['sai']} ({100 * v['sai'] / t:.0f}%)")
        print(f"   không tách (để nguyên): {v['khong_tach_duoc']} ({100 * v['khong_tach_duoc'] / t:.0f}%)")
        for ph, r in v["vi_du_sai"]:
            print("   sai:", ph, "->", r)
    elif a.cmd == "run":
        run()
    elif a.cmd == "apply":
        print(f"Đã thay {apply()} file trong {ef.TEXT} (bản gốc lưu ở {backup_dir()})")
    elif a.cmd == "revert":
        print(f"Đã khôi phục {revert()} file")


if __name__ == "__main__":
    main()

"""Chuẩn hóa văn bản của crawl_v2 theo bốn nhóm, trong MỘT file.

  1. Làm sạch cấu trúc và định dạng
  2. Chuẩn hóa ký tự và mã hóa
  3. Chuẩn hóa chính tả và cách viết
  4. Chuẩn hóa ngày, số, đơn vị

Thứ tự CHẠY là 2 -> 1 -> 3 -> 4 (nhóm 2 trước để các quy tắc cấu trúc nhìn thấy ký tự đã sạch).
Mỗi quy tắc có tên dạng "<nhóm>.<tên>", ghi lại từng thay đổi vào extract/normalize_changes.csv
và có thể bật/tắt theo nhóm bằng --groups.

Không sửa file nguồn: đọc dữ liệu qua extract_files.merge() (dùng chữ OCR đã qua fix_ocr nếu có
trong extract/text_fixed), ghi kết quả ra data/crawl_v2_clean.json.

Lệnh:
  python normalize.py run [--groups 1,2,3,4] [--raw-ocr]
  python normalize.py test        # kiểm tra từng quy tắc trên ví dụ + tính lũy đẳng
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import extract_files as ef

ROOT = Path(__file__).resolve().parent
EXT = ROOT / "extract"
TEXT_FIXED = EXT / "text_fixed"
OUT_JSON = ROOT / "data" / "crawl_v2_clean.json"
CHANGES = EXT / "normalize_changes.csv"
LOG = EXT / "normalize_log.csv"

FIELDS = ("title", "content", "extracted_text")
SNIP = 120

# ------------------------------------------------------------------ hạ tầng quy tắc
RULES: list[tuple[str, str, object]] = []        # (nhóm, tên đầy đủ, hàm)


def rule(group: int, name: str, fields=FIELDS):
    def deco(fn):
        fn.fields = fields
        RULES.append((str(group), f"{group}.{name}", fn))
        return fn
    return deco


class Ctx:
    """Thu thập sự kiện thay đổi của một trường văn bản."""

    def __init__(self, allowed=None):
        self.events: list[tuple[str, str, str]] = []
        self.allowed = allowed

    def add(self, name, before, after):
        self.events.append((name, before[:SNIP], after[:SNIP]))


def _sub(rx, repl, text, ctx, name):
    def f(m):
        new = repl(m) if callable(repl) else m.expand(repl)
        if new != m.group(0):
            ctx.add(name, m.group(0), new)
        return new
    return rx.sub(f, text)


def _lines(fn, text, ctx, name):
    out = []
    for ln in text.split("\n"):
        new = fn(ln)
        if new != ln:
            ctx.add(name, ln, new)
        out.append(new)
    return "\n".join(out)


# ================================================================== NHÓM 2: ký tự và mã hóa
@rule(2, "nfc")
def r_nfc(t, ctx):
    return _lines(lambda l: unicodedata.normalize("NFC", l), t, ctx, "2.nfc")


INVISIBLE = re.compile("[​‌‍⁠﻿­]")
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ODD_SPACE = re.compile("[   -   　]")


@rule(2, "invisible")
def r_invisible(t, ctx):
    return _sub(INVISIBLE, "", t, ctx, "2.invisible")


@rule(2, "line_ending")
def r_cr(t, ctx):
    if "\r" in t:
        ctx.add("2.line_ending", "\\r", "\\n")
    return t.replace("\r\n", "\n").replace("\r", "\n")


@rule(2, "control")
def r_control(t, ctx):
    return _sub(CONTROL, "", t, ctx, "2.control")


@rule(2, "space")
def r_space(t, ctx):
    return _sub(ODD_SPACE, " ", t, ctx, "2.space")


QUOTES = {"“": '"', "”": '"', "‘": "'", "’": "'"}
DASHES = re.compile("[‐-―−]")


@rule(2, "quote")
def r_quote(t, ctx):
    return _sub(re.compile("[“”‘’]"), lambda m: QUOTES[m.group(0)], t, ctx, "2.quote")


@rule(2, "dash")
def r_dash(t, ctx):
    return _sub(DASHES, "-", t, ctx, "2.dash")


@rule(2, "ellipsis")
def r_ellipsis(t, ctx):
    return _sub(re.compile("…"), "...", t, ctx, "2.ellipsis")


@rule(2, "stray_char")
def r_stray(t, ctx):
    """Xóa ký tự không xuất hiện trong bất kỳ văn bản sạch nào (xem build_allowed)."""
    allowed = ctx.allowed
    if allowed is None:
        return t
    return "".join(
        ch if (ch in allowed or ch in "\n\t") else (ctx.add("2.stray_char", ch, "") or "")
        for ch in t)


# ================================================================== NHÓM 1: cấu trúc và định dạng
CID = re.compile(r"\(cid:\d+\)")
BULLET = re.compile(r"^([ \t]*)[•·▪●○■◦►✓✔➢][ \t]*")


@rule(1, "cid")
def r_cid(t, ctx):
    return _sub(CID, " ", t, ctx, "1.cid")


@rule(1, "bullet")
def r_bullet(t, ctx):
    return _lines(lambda l: BULLET.sub(r"\1- ", l), t, ctx, "1.bullet")


SUB_LIST = re.compile(r"^[ \t]+\+[ \t]+(?=[^\W\d_])")


@rule(1, "sub_list")
def r_sub_list(t, ctx):
    """Dòng danh sách con thụt lề '  + Mục' -> '- Mục' (cùng ký hiệu với các danh sách khác)."""
    return _lines(lambda l: SUB_LIST.sub("- ", l), t, ctx, "1.sub_list")


@rule(1, "indent", fields=("extracted_text",))
def r_indent(t, ctx):
    """Bỏ dấu cách đầu dòng của chữ trích từ PDF: thụt lề ở đó chỉ là vị trí trên trang,
    không mang cấu trúc (nội dung website không có thụt lề kiểu này)."""
    return _lines(lambda l: l.lstrip(" 	"), t, ctx, "1.indent")


@rule(1, "trailing_space")
def r_trailing(t, ctx):
    return _lines(lambda l: l.rstrip(" \t"), t, ctx, "1.trailing_space")


MULTI = re.compile(r"(?<=\S)[ \t]{2,}")


@rule(1, "multi_space")
def r_multispace(t, ctx):
    return _lines(lambda l: MULTI.sub(" ", l), t, ctx, "1.multi_space")


HAS_ALNUM = re.compile(r"[^\W_]")


@rule(1, "symbol_line")
def r_symbol_line(t, ctx):
    """Xóa dòng không có chữ hoặc số nào (đường kẻ, ký hiệu rời)."""
    out = []
    for ln in t.split("\n"):
        if ln.strip() and not HAS_ALNUM.search(ln):
            ctx.add("1.symbol_line", ln, "")
            continue
        out.append(ln)
    return "\n".join(out)


LOWER_START = re.compile(r"^[a-zà-ỹ]")
END_STOP = re.compile(r"[.;:!?)\]|]$")


WRAP_RATIO = 0.85


@rule(1, "rewrap", fields=("extracted_text",))
def r_rewrap(t, ctx):
    """Nối dòng bị PDF ngắt giữa câu. Điều kiện: dòng trước không kết thúc bằng dấu câu/bảng,
    dòng sau bắt đầu bằng chữ thường, không phải dòng bảng/danh sách, và dòng trước dài
    ≥ 85% độ dài dòng thường (phân vị 90 của tài liệu) - dòng bị ngắt thật nằm sát lề phải,
    còn mảnh ô bảng thì ngắn."""
    lines = t.split("\n")
    lens = sorted(len(l) for l in lines if l.strip() and " | " not in l)
    if len(lens) < 20:
        return t
    min_len = WRAP_RATIO * lens[int(len(lens) * 0.9)]
    out = []
    prev_len = 0                                    # độ dài dòng vật lý trước, không phải dòng đã nối
    for ln in lines:
        if out:
            prev = out[-1]
            if (prev.strip() and ln.strip()
                    and prev_len >= min_len
                    and not END_STOP.search(prev.rstrip())
                    and LOWER_START.match(ln)
                    and " | " not in prev and " | " not in ln
                    and not prev.lstrip().startswith(("- ", "#"))):
                ctx.add("1.rewrap", prev[-60:] + " ⏎ " + ln[:60], "")
                out[-1] = prev + " " + ln
                prev_len = len(ln)
                continue
        out.append(ln)
        prev_len = len(ln)
    return "\n".join(out)


@rule(1, "blank_lines")
def r_blank(t, ctx):
    new = re.sub(r"\n{3,}", "\n\n", t).strip("\n")
    if new != t:
        ctx.add("1.blank_lines", "(dòng trống thừa)", "")
    return new


# ================================================================== NHÓM 3: chính tả và cách viết
TONE_MARKS = {0x0300, 0x0301, 0x0309, 0x0303, 0x0323}
LETTER_RUN = re.compile(r"[^\W\d_]+")


def _units(word):
    units = []
    for ch in unicodedata.normalize("NFD", word):
        if unicodedata.combining(ch):
            units[-1][1].append(ch)
        else:
            units.append([ch, []])
    return units


def tone_on_first(word):
    """Đặt dấu thanh của vần mở oa/oe/uy lên chữ cái đầu của vần (hòa, khóa, khỏe, thủy)."""
    if not any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", word)):
        return word
    u = _units(word)
    if len(u) < 2:
        return word
    pair = (u[-2][0] + u[-1][0]).lower()
    if pair not in ("oa", "oe", "uy"):
        return word
    if pair == "uy" and len(u) >= 3 and u[-3][0].lower() == "q":
        return word                                     # qu + y: dấu chỉ có thể ở y
    first, second = u[-2], u[-1]
    tone = lambda x: [c for c in x[1] if ord(c) in TONE_MARKS]
    other = lambda x: [c for c in x[1] if ord(c) not in TONE_MARKS]
    if other(first) or other(second):
        return word                                     # có ă â ê ô ơ ư: không đụng
    if not tone(second) or tone(first):
        return word
    first[1] = first[1] + tone(second)
    second[1] = []
    return unicodedata.normalize("NFC", "".join(c + "".join(m) for c, m in u))


@rule(3, "tone_placement")
def r_tone(t, ctx):
    return _sub(LETTER_RUN, lambda m: tone_on_first(m.group(0)), t, ctx, "3.tone_placement")


KI = {"kĩ": "kỹ", "Kĩ": "Kỹ", "KĨ": "KỸ", "kỉ": "kỷ", "Kỉ": "Kỷ", "KỈ": "KỶ",
      "kì": "kỳ", "Kì": "Kỳ", "KÌ": "KỲ"}
KI_RX = re.compile(r"(?<![^\W\d_])(" + "|".join(KI) + r")(?![^\W\d_])")


@rule(3, "i_y")
def r_iy(t, ctx):
    return _sub(KI_RX, lambda m: KI[m.group(1)], t, ctx, "3.i_y")


# ================================================================== NHÓM 4: ngày, số, đơn vị
DATE_RX = re.compile(r"(?<![\d/.])(\d{1,2})([/\-])(\d{1,2})\2(\d{4})(?![\d/\-])")


def _date(m):
    if m.group(2) == "-" and m.string[max(0, m.start() - 2):m.start()][-1:] == "-" and m.string[m.start() - 2:m.start() - 1].isdigit():
        return m.group(0)                            # '2024-11-05'-kiểu: dấu '-' trước là phân cách của số khác
    d, mo, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
    try:
        date(y, mo, d)
    except ValueError:
        return m.group(0)
    if not 1900 <= y <= 2100:
        return m.group(0)
    return f"{d:02d}/{mo:02d}/{y}"


DATE_RANGE = re.compile(r"(?<![\d/.])(\d{1,2}/\d{1,2}/\d{4})([ 	]*-[ 	]*)(\d{1,2}/\d{1,2}/\d{4})(?![\d/])")


def _fmt_date(s):
    d, mo, y = (int(x) for x in s.split("/"))
    try:
        date(y, mo, d)
    except ValueError:
        return s
    return f"{d:02d}/{mo:02d}/{y}" if 1900 <= y <= 2100 else s


@rule(4, "date")
def r_date(t, ctx):
    t = _sub(DATE_RANGE, lambda m: _fmt_date(m.group(1)) + m.group(2) + _fmt_date(m.group(3)), t, ctx, "4.date")
    return _sub(DATE_RX, _date, t, ctx, "4.date")


YEAR_RANGE = re.compile(r"(?<![\w/.\-])(20\d\d)[ \t]*[-–—][ \t]*(20\d\d)(?![\w/.\-])")


@rule(4, "year_range")
def r_year_range(t, ctx):
    def f(m):
        gap = int(m.group(2)) - int(m.group(1))
        return f"{m.group(1)} - {m.group(2)}" if 0 <= gap <= 10 else m.group(0)
    return _sub(YEAR_RANGE, f, t, ctx, "4.year_range")


FOREIGN_SCALE = re.compile(r"IELTS|TOEFL|TOEIC|HSK|JLPT|TOPIK|GPA|CEFR|Cambridge|PTE", re.I)
DEC_POINT = re.compile(r"(?<![\d.,/])(\d{1,3})\.(\d{1,2})(?!\d)(?=[ \t]*(?:năm\b|điểm\b|tín chỉ\b|tháng\b|học kỳ\b|%))")


@rule(4, "decimal_comma")
def r_decimal(t, ctx):
    """3.5 năm -> 3,5 năm (dấu thập phân là dấu phẩy); bỏ qua điểm chứng chỉ ngoại ngữ (IELTS 6.5)."""
    def line(ln):
        def f(m):
            if FOREIGN_SCALE.search(ln[:m.start()][-30:]):
                return m.group(0)
            return f"{m.group(1)},{m.group(2)}"
        return DEC_POINT.sub(f, ln)
    return _lines(line, t, ctx, "4.decimal_comma")


@rule(4, "percent")
def r_percent(t, ctx):
    return _sub(re.compile(r"(\d)[ \t]+%"), r"\1%", t, ctx, "4.percent")


NOT_LETTER = r"(?![^\W\d_])"
MONEY_NUM = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+)[ \t]*(?:VNĐ|VND|vnđ|vnd|Vnđ|đ|Đ)" + NOT_LETTER)
MONEY_MAG = re.compile(r"\b(triệu|tỷ|nghìn|ngàn)[ \t]+(?:VNĐ|VND|vnđ|vnd|Vnđ)" + NOT_LETTER)


@rule(4, "currency")
def r_currency(t, ctx):
    """Ký hiệu tiền: đ / Đ / VND / vnđ -> VNĐ, luôn có dấu cách sau số. Chữ 'đồng' giữ nguyên."""
    t = _sub(MONEY_NUM, r"\1 VNĐ", t, ctx, "4.currency")
    return _sub(MONEY_MAG, r"\1 VNĐ", t, ctx, "4.currency")


TC = re.compile(r"(?<=\d)[ \t]?TC\b|\bSố TC\b|\bTổng số TC\b")


@rule(4, "credit_unit")
def r_tc(t, ctx):
    """'3 TC' -> '3 tín chỉ', 'Số TC' -> 'Số tín chỉ'."""
    def f(m):
        s = m.group(0)
        return s.replace("TC", "tín chỉ") if s.startswith(("Số", "Tổng")) else " tín chỉ"
    return _sub(TC, f, t, ctx, "4.credit_unit")


# ------------------------------------------------------------------ thực thi
RUN_ORDER = ["2", "1", "3", "4"]


SKIP: set = set()


def normalize_text(text, field, ctx, groups=("1", "2", "3", "4")):
    for g in RUN_ORDER:
        if g not in groups:
            continue
        for grp, name, fn in RULES:
            if grp == g and field in fn.fields and name not in SKIP:
                text = fn(text, ctx)
    return text


def build_allowed(records):
    """Ký tự hợp lệ = ASCII + mọi ký tự đã gặp trong văn bản sạch (nội dung website và
    file không qua OCR), sau khi NFC. Ký tự ngoài tập này chỉ có thể là nhiễu OCR."""
    allowed = {chr(c) for c in range(32, 127)}
    for r in records:
        srcs = [r.get("title", ""), r.get("content", "")]
        if r.get("extract_method") and "ocr" not in r["extract_method"] and "(cid:" not in r.get("extracted_text", ""):
            srcs.append(r.get("extracted_text", ""))
        for s in srcs:
            allowed.update(unicodedata.normalize("NFC", s))
    return allowed


class _Overlay:
    """`TEXT / name` -> bản đã sửa OCR nếu có, ngược lại bản trích xuất gốc."""

    def __init__(self, raw, fixed):
        self.raw, self.fixed = raw, fixed

    def __truediv__(self, name):
        p = self.fixed / name
        return p if p.exists() else self.raw / name


def load_input(use_fixed=True):
    orig_text, orig_out = ef.TEXT, ef.OUT
    tmp = Path(tempfile.mkdtemp()) / "merged.json"
    try:
        if use_fixed and TEXT_FIXED.exists():
            ef.TEXT = _Overlay(orig_text, TEXT_FIXED)
        ef.OUT = tmp                               # không ghi đè data/crawl_v2_extracted.json
        merged, _ = ef.merge()
    finally:
        ef.TEXT, ef.OUT = orig_text, orig_out
    return merged


def run(groups=("1", "2", "3", "4"), use_fixed=True):
    records = load_input(use_fixed)
    allowed = build_allowed(records) if "2" in groups else None
    rows, per_rule, docs_of = [], Counter(), defaultdict(set)
    before_chars = after_chars = 0
    out = []
    for r in records:
        r2 = dict(r)
        for f in FIELDS:
            src = r.get(f) or ""
            if not src:
                continue
            ctx = Ctx(allowed)
            new = normalize_text(src, f, ctx, groups)
            r2[f] = new
            before_chars += len(src)
            after_chars += len(new)
            for name, b, a in ctx.events:
                rows.append((r["id"], f, name, b, a))
                per_rule[name] += 1
                docs_of[name].add(r["id"])
        out.append(r2)

    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with CHANGES.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["record_id", "field", "rule", "before", "after"])
        w.writerows(rows)
    with LOG.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rule", "n_changes", "n_records"])
        for name in sorted(per_rule):
            w.writerow([name, per_rule[name], len(docs_of[name])])

    print(f"{len(out)} bản ghi, {before_chars:,} -> {after_chars:,} ký tự")
    for name in sorted(per_rule):
        print(f"  {name:22s} {per_rule[name]:>7,} thay đổi / {len(docs_of[name]):>3} bản ghi")
    stray = Counter(b for _, _, n, b, _ in rows if n == "2.stray_char")
    if stray:
        print("  ký tự lạ bị xóa nhiều nhất:", " ".join(f"{c}×{n}" for c, n in stray.most_common(15)))
    print(f"-> {OUT_JSON}\n-> {CHANGES}\n-> {LOG}")
    return out


# ------------------------------------------------------------------ kiểm tra
def _apply(text, field="extracted_text", groups=("1", "2", "3", "4"), allowed=None):
    ctx = Ctx(allowed)
    return normalize_text(text, field, ctx, groups), ctx


def test():
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(("PASS " if good else "FAIL ") + label + ("" if good else f"\n   got : {got!r}\n   want: {want!r}"))

    A = set("abcdefghijklmnopqrstuvwxyz ")
    check("2 NFC", _apply("Tiếng")[0], unicodedata.normalize("NFC", "Tiếng"))
    check("2 nbsp + zero width", _apply("a b​c")[0], "a bc")
    check("2 CRLF", _apply("a\r\nb")[0], "a\nb")
    check("2 quote/dash/ellipsis", _apply("“A” – b…")[0], '"A" - b...')
    check("2 stray char", _apply("abc ¡¬ def", allowed=A | {"\n"})[0], "abc def")
    check("1 cid", _apply("Số:(cid:9) /QĐ")[0], "Số: /QĐ")
    check("1 bullet", _apply("▪ Lưu ý")[0], "- Lưu ý")
    check("1 sub_list", _apply("Thi:\n  + Âm nhạc 1\n  + Âm nhạc 2")[0], "Thi:\n- Âm nhạc 1\n- Âm nhạc 2")
    check("1 sub_list không đụng '+ 5'", _apply("a\n  + 5 điểm", field="content")[0], "a\n  + 5 điểm")
    check("3 kì/kỳ", _apply("bất kì lúc, Kì thi, KÌ, kìa, học kỳ")[0], "bất kỳ lúc, Kỳ thi, KỲ, kìa, học kỳ")
    check("1 multi_space", _apply("a    b")[0], "a b")
    check("1 symbol_line", _apply("a\n———\n| |\nb")[0], "a\nb")
    check("1 symbol_line giữ dòng có số", _apply("a\n- 5\nb")[0], "a\n- 5\nb")
    fill = "\n".join(["Dòng văn xuôi đủ dài để làm chuẩn độ dài của tài liệu thử nghiệm này nhé."] * 25) + "\n"
    long_line = "Căn cứ Luật Giáo dục đại học số 08 ngày 18 tháng 6 năm 2012 và các văn bản"
    last = lambda s, k=1, **kw: _apply(s, **kw)[0].split("\n")[-k:]
    check("1 rewrap nối", last(fill + long_line + "\nbổ sung một số điều"), [long_line + " bổ sung một số điều"])
    check("1 rewrap không nối khi hết câu", last(fill + long_line + ".\nbổ sung", 2), [long_line + ".", "bổ sung"])
    check("1 rewrap không nối mảnh ngắn", last(fill + "Phương pháp học X\nnhóm", 2), ["Phương pháp học X", "nhóm"])
    check("1 rewrap không nối dòng bảng", last(fill + long_line + " | 3 | 45\nthực hành"), ["thực hành"])
    check("1 rewrap không áp dụng cho content", last(fill + long_line + "\nbổ sung", field="content"), ["bổ sung"])
    check("1 blank", _apply("\n\na\n\n\n\nb\n\n")[0], "a\n\nb")
    for w, e in [("hoà", "hòa"), ("khoá", "khóa"), ("Khoá", "Khóa"), ("thuỷ", "thủy"), ("khoẻ", "khỏe"),
                 ("HOÁ", "HÓA"), ("toán", "toán"), ("quỹ", "quỹ"), ("hoạt", "hoạt"), ("khóa", "khóa"), ("tuỳ", "tùy")]:
        check(f"3 tone {w}", _apply(w)[0], e)
    check("3 kĩ/kỉ", _apply("kĩ thuật, Kĩ năng, kỉ luật, kĩnăng")[0], "kỹ thuật, Kỹ năng, kỷ luật, kĩnăng")
    check("4 date pad", _apply("từ 5/9/2025 đến 15/10/2025")[0], "từ 05/09/2025 đến 15/10/2025")
    check("4 date dash", _apply("ngày 29-11-2024")[0], "ngày 29/11/2024")
    check("4 date khoảng ngày", _apply("5/01/2026-16/01/2026 | 7/1/2026 - 8/1/2026")[0], "05/01/2026-16/01/2026 | 07/01/2026 - 08/01/2026")
    check("1 indent chỉ cho extracted_text", [_apply("  a b")[0], _apply("  a b", field="content")[0]], ["a b", "  a b"])
    check("4 date sau dấu gạch", _apply("Đợt 1: 28/6:-25/7/2027; Đợt 2: 26/7 -22/8/2027")[0], "Đợt 1: 28/6:-25/07/2027; Đợt 2: 26/7 -22/08/2027")
    check("4 date khoảng rút gọn", _apply("GVHD từ 14-17/9/2026; (03-07/8/2026)")[0], "GVHD từ 14-17/09/2026; (03-07/08/2026)")
    check("4 date '-' không ăn vào số khác", _apply("mã 12-5-3-2024")[0], "mã 12-5-3-2024")
    check("4 date invalid", _apply("31/02/2025 và 12/13/2025")[0], "31/02/2025 và 12/13/2025")
    check("4 date không đụng ngày dài", _apply("ngày 12 tháng 6 năm 2026")[0], "ngày 12 tháng 6 năm 2026")
    check("4 year_range", _apply("2025-2026; 2025 – 2026; 2025–2026")[0], "2025 - 2026; 2025 - 2026; 2025 - 2026")
    check("4 decimal", _apply("Thời gian học: 3.5 năm; 16.00 điểm; 21.5%")[0], "Thời gian học: 3,5 năm; 16,00 điểm; 21,5%")
    check("4 decimal giữ IELTS", _apply("IELTS 6.5 điểm")[0], "IELTS 6.5 điểm")
    check("4 decimal giữ số mục", _apply("2.1.3. Các")[0], "2.1.3. Các")
    check("4 percent", _apply("chiếm 52 %")[0], "chiếm 52%")
    check("4 currency", _apply("450.000VNĐ/sv; 70.000 đ/bữa; 1.100.000đ; 42.8 triệu vnđ")[0],
          "450.000 VNĐ/sv; 70.000 VNĐ/bữa; 1.100.000 VNĐ; 42.8 triệu VNĐ")
    check("4 currency giữ đồng", _apply("20.000.000 đồng")[0], "20.000.000 đồng")
    check("4 TC", _apply("Chọn 3 TC/9 TC sau; Số TC")[0], "Chọn 3 tín chỉ/9 tín chỉ sau; Số tín chỉ")
    check("4 TC không đụng chữ khác", _apply("ATC 5")[0], "ATC 5")

    sample = ("Khoá 39 từ 5/9/2025\n▪ Học phí: 20.400.000đ/kỳ (3.5 năm)\n\n\n"
              "Căn cứ Luật Giáo dục đại học số 08 ngày\nbổ sung kĩ thuật  52 %\n")
    once, _ = _apply(sample)
    twice, c2 = _apply(once)
    check("lũy đẳng (chạy lần 2 không đổi gì)", twice, once)
    print("TẤT CẢ PASS" if ok else "CÓ LỖI")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "test"])
    ap.add_argument("--groups", default="1,2,3,4")
    ap.add_argument("--skip", default="", help="tắt riêng quy tắc, ví dụ 1.rewrap,4.credit_unit")
    ap.add_argument("--raw-ocr", action="store_true", help="dùng chữ OCR gốc, không dùng extract/text_fixed")
    a = ap.parse_args(argv)
    if a.cmd == "test":
        sys.exit(0 if test() else 1)
    SKIP.update(x.strip() for x in a.skip.split(",") if x.strip())
    run(tuple(x.strip() for x in a.groups.split(",")), use_fixed=not a.raw_ocr)


if __name__ == "__main__":
    main()

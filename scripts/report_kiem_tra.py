"""Xuất data/processed/kiem_tra_15.md: hồ sơ đọc nhanh cho các tài liệu có `can_kiem_tra` trong configs/doc_meta.yaml.

CHỈ ĐỌC doc_meta.yaml và data/interim/clean; chỉ GHI data/processed/kiem_tra_15.md.
    python scripts/report_kiem_tra.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from rag.chunking.loader import build_document  # noqa: E402
from rag.chunking.procedural import extract_issued_date, filter_document  # noqa: E402
from rag.config import chunking_config  # noqa: E402

KEYWORDS = ["thay thế", "bãi bỏ", "hết hiệu lực", "sửa đổi", "bổ sung", "có hiệu lực", "trở đi", "các khóa", "khóa", "áp dụng"]
MAX_HITS = 14          # số đoạn trích tối đa mỗi tài liệu
MAX_ARTICLE = 2500     # cắt Điều quá dài khi in
REFERENCE_ONLY = ["drive-17fWyMLcyA1LpaqxEMnaMGmHoTKpYqbs6"]  # đối chiếu nhóm B, không có can_kiem_tra
FIXED_PREFIXES = ("drive-1-YrDG1q", "drive-11kscJT", "drive-13k1p5G", "drive-1BP-a2j", "drive-1fAwLCo", "drive-1ksklvK", "drive-1fBG2yz",
                  "drive-1GfS8mV", "drive-1gYObSE", "drive-1KfxA1E", "drive-1nBaNul", "drive-1okFSxr", "drive-1Q0FM6L", "drive-1rUr8Uo",
                  "drive-1RW4A1I")
SIGNS = ["Họ và tên", "Họ tên", "Mã SV", "Mã sinh viên", "Ngày sinh", "Lớp"]
RE_DOB = re.compile(r"(?<!ngày )(?<!ngày\xa0)\b\d{1,2}[/.-]\d{1,2}[/.-](?:19[89]\d|200\d)\b")
RE_ID = re.compile(r"\b(?:[A-Z]{1,2}\d{4,8}|\d{7,10})\b")
RE_NAME = re.compile(r"(?:[A-ZÀ-Ỹ][a-zà-ỹ]+\s+){1,}[A-ZÀ-Ỹ][a-zà-ỹ]+|(?:[A-ZÀ-Ỹ]{2,}\s+){1,}[A-ZÀ-Ỹ]{2,}")
RE_SO = re.compile(r"Số\s*:\s*([^\n|]{3,40})")
RE_ART = re.compile(r"^\s*Điều\s+(\d+)\s*[.:]", re.M)


def sentences(text: str) -> list[tuple[int, int]]:
    """Các câu (đoạn) theo vị trí ký tự: tách ở dấu chấm/chấm phẩy/xuống đoạn."""
    out, last = [], 0
    for m in re.finditer(r"(?<=[.;!?])\s+|\n\s*\n", text):
        if m.start() > last:
            out.append((last, m.start()))
        last = m.end()
    if last < len(text):
        out.append((last, len(text)))
    return out


def one_line(s: str, limit: int = 700) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[:limit] + "…"


def keyword_hits(text: str) -> tuple[Counter, list[str]]:
    sents = sentences(text)
    counts: Counter = Counter()
    hits: list[tuple[int, str, str]] = []
    for i, (a, b) in enumerate(sents):
        s = text[a:b].lower()
        found = [k for k in KEYWORDS if k in s]
        if not found:
            continue
        counts.update(found)
        # từ khóa cụ thể nhất (đứng đầu danh sách) quyết định thứ tự ưu tiên
        prio = min(KEYWORDS.index(k) for k in found)
        prev = one_line(text[sents[i - 1][0]:sents[i - 1][1]], 300) if i else ""
        nxt = one_line(text[sents[i + 1][0]:sents[i + 1][1]], 300) if i + 1 < len(sents) else ""
        hits.append((prio, ", ".join(found), f"…{prev}\n> **[{one_line(text[a:b], 500)}]**\n> {nxt}…"))
    hits.sort(key=lambda h: h[0])  # ổn định: giữ thứ tự xuất hiện trong cùng mức ưu tiên
    chosen = hits[:MAX_HITS]
    return counts, [f"- *({k})*\n> {body}" for _, k, body in chosen] + ([f"- … còn {len(hits) - MAX_HITS} đoạn khác"] if len(hits) > MAX_HITS else [])


def articles_of_decision(text: str) -> tuple[tuple[int, str] | None, tuple[int, str] | None, int]:
    """(Điều đầu, Điều cuối, số khối đánh số lại) của phần Quyết định = khối Điều đầu tiên (đến khi số Điều quay về nhỏ hơn)."""
    marks = [(m.start(), int(m.group(1))) for m in RE_ART.finditer(text)]
    if not marks:
        return None, None, 0
    block, prev = [marks[0]], marks[0][1]
    blocks = 1
    for pos, no in marks[1:]:
        if no <= prev:
            blocks += 1
            break
        block.append((pos, no))
        prev = no

    def body(idx: int) -> tuple[int, str]:
        start = block[idx][0]
        end = block[idx + 1][0] if idx + 1 < len(block) else len(text)
        if idx + 1 == len(block):  # Điều cuối: dừng ở khối chữ ký/phụ lục
            fr_end = re.search(r"^\s*(nơi nhận|phụ lục|quy chế\b|chương\s+[ivxlc]+\b|\(?(ban hành )?kèm theo|\||[ivx1]\.\s+danh sách|1\.\s+ngành)", text[start:], re.I | re.M)
            if fr_end and fr_end.start() > 0:
                end = start + fr_end.start()
        return block[idx][1], text[start:end].strip()

    return body(0), body(len(block) - 1), blocks


NAME_HEADER = re.compile(r"họ\s*(và\s*)?tên", re.I)
CELL_NAME = re.compile(r"^(?:[A-ZÀ-Ỹ][a-zà-ỹ]+\s+){1,5}[A-ZÀ-Ỹ][a-zà-ỹ]+$|^(?:[A-ZÀ-Ỹ]{2,}\s+){1,5}[A-ZÀ-Ỹ]{2,}$")


def _cells(line: str) -> list[str]:
    parts = line.strip().split("|")
    return parts[1:-1] if len(parts) >= 3 and line.strip().endswith("|") else parts[1:]


def mask_text(text: str) -> str:
    """Che họ tên trong MỌI bảng: (1) ô thuộc cột có tiêu đề "Họ và tên"/"Họ tên"; (2) dự phòng: ô trông như tên người
    (2-6 từ viết hoa chữ cái đầu) trong dòng bảng có mã SV/ngày sinh (bảng OCR/PDF lệch cột). Văn bản thường không bị đổi."""
    out, name_cols, in_table = [], set(), False
    for line in text.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            out.append(line)
            in_table, name_cols = False, set()
            continue
        cells = _cells(line)
        if not in_table or any(NAME_HEADER.search(c) for c in cells):
            hdr = {i for i, c in enumerate(cells) if NAME_HEADER.search(c)}
            if hdr:
                name_cols = hdr
        in_table = True
        has_id = bool(RE_ID.search(line) or RE_DOB.search(line))
        new = []
        for i, c in enumerate(cells):
            t = c.strip()
            hit = t and not NAME_HEADER.search(t) and ((i in name_cols and not re.fullmatch(r"[\d\W_]+", t)) or (has_id and CELL_NAME.match(t)))
            new.append(" *** " if hit else c)
        out.append("|" + "|".join(new) + "|")
    return "\n".join(out)


def mask(line: str) -> str:
    return line


def personal_signs(text: str) -> dict:
    present = {s: len(re.findall(re.escape(s), text, re.I)) for s in SIGNS}
    lines = [l for l in text.split("\n") if l.strip()]
    stu = [l for l in lines if RE_DOB.search(l) or (RE_ID.search(l) and (l.lstrip().startswith("|") or re.match(r"^\s*\d+\s", l)))]
    both = [l for l in stu if RE_DOB.search(l) and RE_ID.search(l)]
    pool = both or stu
    step = max(1, len(pool) // 3)
    samples = [mask(one_line(pool[i], 220)) for i in range(0, len(pool), step)][:3]
    return {"present": present, "n_stu": len(stu), "n_dob": sum(bool(RE_DOB.search(l)) for l in lines),
            "n_id": sum(bool(RE_ID.search(l)) for l in stu), "samples": samples}


def shingles(text: str, n: int = 5) -> set[int]:
    w = re.findall(r"\w+", text.lower())
    return {hash(" ".join(w[i:i + n])) for i in range(max(1, len(w) - n + 1))}


def group_of(title: str, doc_id: str) -> str:
    t = (title or "").lower()
    if doc_id in REFERENCE_ONLY or "quy chế tuyển sinh" in t:
        return "B"
    if "quy chế đào tạo trình độ đại học" in t:
        return "A"
    if "chuyển ngành, chuyển chuyên ngành, học ngành hai" in t:
        return "C"
    return "D"


GROUP_TITLE = {"A": "(A) Quy chế đào tạo trình độ đại học", "B": "(B) Quy chế tuyển sinh", "C": "(C) Quy định chuyển ngành, chuyển chuyên ngành, học ngành hai",
               "D": "(D) Các tài liệu còn lại"}


def main() -> None:
    cfg = chunking_config()
    raw = yaml.safe_load(cfg["paths"]["doc_meta"].read_text(encoding="utf-8"))["docs"]
    flagged = [d for d, e in raw.items() if e.get("can_kiem_tra")]
    if not flagged:  # doc_meta.yaml đã chốt, không còn can_kiem_tra: dùng danh sách cố định của báo cáo 15 tài liệu
        flagged = [d for d in raw if d.startswith(FIXED_PREFIXES)]
    want = flagged + [d for d in REFERENCE_ONLY if d in raw and d not in flagged]
    info: dict[str, dict] = {}
    for p in sorted(cfg["paths"]["clean_dir"].glob("*.json")):
        if p.name == "_manifest.json":
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        doc = build_document(data)
        fr = filter_document(doc.text)
        info[doc.doc_id] = {"data": data, "doc": doc, "fr": fr, "sha": data.get("extract_input_sha256"),
                            "h": hashlib.sha256(doc.text.encode()).hexdigest(),
                            "hb": hashlib.sha256(re.sub(r"\s+", " ", fr.ftext).strip().lower().encode()).hexdigest()}

    def duplicates(d: str) -> list[str]:
        out = []
        for o, v in info.items():
            if o == d:
                continue
            why = []
            if v["sha"] and v["sha"] == info[d]["sha"]:
                why.append("cùng extract_input_sha256")
            if v["h"] == info[d]["h"]:
                why.append("văn bản chuẩn hóa giống hệt")
            elif v["hb"] == info[d]["hb"]:
                why.append("phần thân giống hệt (sau khi bỏ phần thủ tục)")
            if why:
                out.append(f"`{o}` — {raw[o]['title'][:70]} ({'; '.join(why)})")
        return out

    lines: list[str] = ["# Kiểm tra 15 tài liệu có `can_kiem_tra`", "",
                        "_Tạo bởi scripts/report_kiem_tra.py. Chỉ đọc doc_meta.yaml và clean/. Họ tên trong mẫu danh sách đã che bằng ***._", ""]
    by_group: dict[str, list[str]] = {g: [] for g in "ABCD"}
    for d in want:
        by_group[group_of(raw[d]["title"], d)].append(d)
    lines += ["## Mục lục", ""]
    for g, ids in by_group.items():
        lines.append(f"- **{GROUP_TITLE[g]}** — {len(ids)} tài liệu")
        for d in ids:
            lines.append(f"  - `{d}` — {raw[d]['title'][:80]}" + ("" if d in flagged else " _(đối chiếu, không có can_kiem_tra)_"))
    lines.append("")
    for g, ids in by_group.items():
        if not ids:
            continue
        lines += [f"# {GROUP_TITLE[g]}", ""]
        if g in "AC" and len(ids) > 1:
            lines += ["**So sánh các bản trong nhóm** (độ giống Jaccard shingle 5 từ / tỉ lệ chứa; chỉ phần thân sau khi lọc thủ tục):", "",
                      "| A | B | Jaccard | A chứa trong B | ngày ban hành A | ngày ban hành B |", "|---|---|---|---|---|---|"]
            sh = {d: shingles(info[d]["fr"].ftext) for d in ids}
            for a, b in combinations(ids, 2):
                i = len(sh[a] & sh[b])
                lines.append(f"| `{a[:18]}` | `{b[:18]}` | {i / max(1, len(sh[a] | sh[b])):.2f} | {i / max(1, len(sh[a])):.2f} | "
                             f"{raw[a]['issued_date']} | {raw[b]['issued_date']} |")
            lines.append("")
        for d in ids:
            e, v = raw[d], info[d]
            text = mask_text(v["doc"].text)
            v["fr"].ftext = mask_text(v["fr"].ftext)  # che tên ở MỌI mục (đoạn trích, Điều, 800 ký tự đầu...)
            lines += [f"## `{d}`", ""]
            lines += [f"1. **Tiêu đề:** {e['title']}",
                      f"   - doc_type `{e['doc_type']}`, in_scope `{e['in_scope']}`, issued_date `{e.get('issued_date')}`, posted_date `{e.get('posted_date')}`",
                      f"   - can_kiem_tra (đã chốt, không còn trong doc_meta): {e.get('ghi_chu_duyet') or '_(tài liệu đối chiếu)_'}",
                      f"   - ghi_chu_duyet: {e.get('ghi_chu_duyet', '—')}",
                      f"   - {len(v['data']['pages'])} trang, {len(text):,} ký tự (đã nối trang, chuẩn hóa); URL: {e.get('source_url')}"]
            dups = duplicates(d)
            lines += [f"2. **extract_input_sha256:** `{v['sha']}`",
                      f"   - hash văn bản chuẩn hóa: `{v['h'][:16]}…` | hash phần thân sau lọc: `{v['hb'][:16]}…`",
                      "   - **Trùng với:** " + ("; ".join(dups) if dups else "không có tài liệu nào trùng hệt")]
            so = RE_SO.search("\n".join(text.split("\n")[:40]))
            lines.append(f"3. **Số hiệu:** {one_line(so.group(1), 60) if so else 'không trích được'} | **Ngày ký:** {extract_issued_date(text) or 'không có ngày đầy đủ'}")
            counts, hits = keyword_hits(v["fr"].ftext)
            lines += ["4. **Câu chứa từ khóa** (đếm số câu: " + ", ".join(f"{k}={counts.get(k, 0)}" for k in KEYWORDS) + ")", ""]
            lines += hits or ["- không có"]
            first, last, blocks = articles_of_decision(v["fr"].ftext)
            lines += ["", f"5. **Điều 1 và Điều cuối của phần Quyết định** (số Điều đánh số lại trong văn bản: {blocks - 1 if blocks else 0} lần)", ""]
            if first is None:
                lines.append("   - _không có “Điều N.”_")
            else:
                for label, (no, body) in (("Điều 1" if first[0] == 1 else f"Điều {first[0]} (đầu)", first), (f"Điều cuối = Điều {last[0]}", last)):
                    if label.startswith("Điều cuối") and last[0] == first[0]:
                        lines.append(f"   - _Điều cuối trùng Điều {first[0]}_")
                        continue
                    lines += [f"   - **{label}:**", "", "     > " + one_line(body, MAX_ARTICLE).replace("\n", "\n     > "), ""]
            ps = personal_signs(text)
            lines += ["6. **Dấu hiệu danh sách cá nhân:** " + ", ".join(f"“{k}”: {n}" for k, n in ps["present"].items()),
                      f"   - dòng giống 1 sinh viên: **{ps['n_stu']}** (có ngày sinh: {ps['n_dob']}, có mã SV: {ps['n_id']})"]
            lines += [f"   - mẫu {i + 1}: `{s}`" for i, s in enumerate(ps["samples"])] or ["   - không có dòng mẫu"]
            fr = v["fr"]
            body_start = fr.preamble[1] if fr.preamble else 0
            lines += ["7. **800 ký tự đầu phần thân** (sau khi bỏ quốc hiệu, tiêu đề và phần căn cứ):", "",
                      "   > " + one_line(fr.ftext[body_start:], 800).replace("\n", " "), "", "---", ""]
    out = cfg["paths"]["out_dir"] / "kiem_tra_15.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(flagged)} tài liệu có can_kiem_tra + {len(want) - len(flagged)} đối chiếu -> {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

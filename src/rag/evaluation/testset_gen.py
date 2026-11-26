"""Sinh câu hỏi đánh giá từ VĂN BẢN TÀI LIỆU (không từ chunk). Dùng bởi scripts/gen_testset.py.

Luồng: chọn đơn vị sinh (Điều/Khoản, mục, nhóm dòng bảng; độc lập ranh giới chunk) -> kế hoạch lời gọi -> dry-run -> gọi LLM
(ghi log thô, chạy tiếp được) -> hậu xử lý (định vị quote, loại tự động, độ trùng từ) -> ghi vào questions.jsonl (review.status=pending).
Phần hậu xử lý (`build_questions`) KHÔNG gọi mạng nên kiểm thử được; LLM được tiêm qua tham số `client`.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import random
import re
import time
from collections import Counter
from pathlib import Path

import yaml

from rag.config import ROOT, load_config
from rag.evaluation import testset as T

# ------------------------------------------------------------------ danh mục tài liệu
GROUP_OF = {"quy_che": "quy_che", "ctdt": "ctdt", "hoc_phi": "hoc_phi", "lich_thi": "lich_thi", "tkb": "tkb", "ke_hoach": "ke_hoach",
            "thong_bao": "thong_bao", "quy_trinh": "khac", "hoc_bong": "khac", "khac": "khac", "mon_thay_the": "khac", "lien_he": "khac"}


def load_doc_meta() -> dict:
    return yaml.safe_load((ROOT / "configs" / "doc_meta.yaml").read_text(encoding="utf-8"))["docs"]


def eligible_docs(meta: dict | None = None, filters: dict | None = None) -> dict[str, dict]:
    """Tài liệu được dùng để sinh câu hỏi: in_scope, không phải bản trùng, khớp default_filters của retrieval (status, bậc), có file văn bản.
    Tài liệu in_scope=false KHÔNG BAO GIỜ được dùng."""
    meta = meta or load_doc_meta()
    f = filters or load_config("retrieval")["default_filters"]
    out = {}
    for d, v in meta.items():
        if not v.get("in_scope") or v.get("trung_voi"):
            continue
        if f.get("status") and v.get("status") != f["status"]:
            continue
        if f.get("bac_dao_tao") and v.get("bac_dao_tao") != f["bac_dao_tao"]:
            continue
        if not (T.DOCS_DIR / f"{d}.txt").exists():
            continue
        out[d] = v
    return out


def vlm_doc_ids() -> set[str]:
    """Tài liệu có trang bảng do VLM đọc (data/interim/table_vlm/<doc_id>.json) - nhóm ablation c2 vs c2_novlm."""
    d = ROOT / "data" / "interim" / "table_vlm"
    return {p.stem for p in d.glob("*.json")} if d.exists() else set()


def quy_che_versions(meta: dict) -> dict[str, str]:
    """{"2024": doc_id, "2025": doc_id, "2026": doc_id} - Quy chế đào tạo đại học còn hiệu lực, đã in_scope, phân theo khóa."""
    out: dict[str, str] = {}
    for d, v in meta.items():
        if v.get("doc_type") != "quy_che" or not v.get("in_scope") or v.get("status") != "hieu_luc" or v.get("trung_voi"):
            continue
        if "Quy chế đào tạo trình độ đại học" not in (v.get("title") or ""):
            continue
        tu, den = v.get("khoa_tu"), v.get("khoa_den")
        if tu is None and den == 37:
            out["2024"] = d
        elif tu == 38 and den == 38:
            out["2025"] = d
        elif tu == 39:
            out["2026"] = d
    return out


def version_of_khoa(khoa: int) -> str:
    return "2024" if khoa <= 37 else ("2025" if khoa == 38 else "2026")


def rep_khoa(v: dict, cfg: dict) -> int | None:
    tu, den = v.get("khoa_tu"), v.get("khoa_den")
    kv = cfg["version_dependent"]["khoa_by_version"]
    if tu is None and den is None:
        return None
    if tu is None:
        return kv["2024"] if den and den <= 37 else den
    if den is None or den >= 60:
        return tu if tu != 39 else kv["2026"]
    return tu if tu == den else kv["2024"] if den <= 37 else tu


# ------------------------------------------------------------------ đơn vị sinh
HEAD_RE = re.compile(r"^(Điều\s+\d+\s*\.|Chương\s+[IVXLC\d]+|Phần\s+[IVXLC\d]+|Mục\s+\d+|[IVX]+\.\s+\S|\d+\.\s+[A-ZĐÀ-Ỹ])", re.U)
DIEU_RE = re.compile(r"^Điều\s+\d+\s*\.", re.U)
BIG_HEAD_RE = re.compile(r"^(Điều\s+\d+\s*\.|Chương\s+[IVXLC\d]+|Phần\s+[IVXLC\d]+|Mục\s+\d+)", re.U)
KHOAN_RE = re.compile(r"^\d+\.\s", re.U)
BOILER = ("CỘNG HÒA XÃ HỘI", "CỘNG HOÀ XÃ HỘI", "Độc lập - Tự do", "Nơi nhận", "Căn cứ ")
KW = {"dieu_kien": re.compile(r"điều kiện|được phép|không được|phải |tối thiểu|tối đa|yêu cầu|tiêu chí|đủ |đạt |áp dụng|đối tượng", re.I),
      "thu_tuc": re.compile(r"hồ sơ|đơn |nộp|bước|thủ tục|đăng ký|trình tự|tại phòng|quy trình|xác nhận|liên hệ", re.I)}


def _lines(text: str) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for ln in text.split("\n"):
        out.append((pos, pos + len(ln), ln))
        pos += len(ln) + 1
    return out


def _alnum_ratio(s: str) -> float:
    return sum(c.isalnum() for c in s) / max(1, len(s))


def _unit(doc_id: str, doc_type: str, s: int, e: int, kind: str, text: str, header: str = "") -> dict:
    return {"unit_id": f"{doc_id}:{s}-{e}", "doc_id": doc_id, "doc_type": doc_type, "char_start": s, "char_end": e, "kind": kind,
            "text": text[s:e], "header": header, "n_digits": len(re.findall(r"\d+", text[s:e]))}


def extract_units(doc_id: str, doc_type: str, text: str, ucfg: dict) -> list[dict]:
    """Đơn vị sinh từ văn bản: bảng -> nhóm dòng; còn lại -> Điều (tách theo Khoản nếu dài) hoặc nhóm dòng giữa hai tiêu đề.
    Độc lập hoàn toàn với ranh giới chunk."""
    lo, hi = ucfg["unit_chars"]
    r_lo, r_hi = ucfg["table_rows"]
    lines = _lines(text)
    units: list[dict] = []
    i = 0
    prose: list[tuple[int, int, str]] = []

    def flush_prose() -> None:
        nonlocal prose
        if prose:
            units.extend(_prose_units(doc_id, doc_type, text, prose, lo, hi))
        prose = []

    while i < len(lines):
        s, e, ln = lines[i]
        if ln.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j][2].lstrip().startswith("|"):
                j += 1
            block = lines[i:j]
            flush_prose()
            units.extend(_table_units(doc_id, doc_type, text, block, r_lo, r_hi, hi))
            i = j
            continue
        prose.append(lines[i])
        i += 1
    flush_prose()
    return [u for u in units if _unit_ok(u, lo)]


def _unit_ok(u: dict, lo: int) -> bool:
    t = u["text"]
    if len(t) < (60 if u["kind"] == "table" else lo):
        return False
    if _alnum_ratio(t) < 0.5:
        return False
    return sum(1 for b in BOILER if b in t) < 2


def _table_units(doc_id, doc_type, text, block, r_lo, r_hi, max_chars):
    sep = re.compile(r"^\s*\|\s*:?-{3,}")
    rows = [b for b in block if not sep.match(b[2])]
    if len(rows) < 2:
        return []
    header = rows[0][2]
    data = rows[1:]
    out, k = [], 0
    n = r_hi
    while k < len(data):
        grp = data[k:k + n]
        while len(grp) > 1 and grp[-1][1] - grp[0][0] > max_chars:
            grp = grp[:-1]
        out.append(_unit(doc_id, doc_type, grp[0][0], grp[-1][1], "table", text, header))
        k += max(1, len(grp))
    return out


def _prose_units(doc_id, doc_type, text, lines, lo, hi):
    """Nhóm dòng văn xuôi: ngắt tại tiêu đề khi đủ dài; Điều dài thì tách theo Khoản; ngắt cứng khi vượt hi."""
    out: list[dict] = []
    cur: list[tuple[int, int, str]] = []
    has_dieu = any(DIEU_RE.match(ln[2].strip()) for ln in lines)
    # văn bản có "Điều": chỉ Điều/Chương/Phần/Mục mở đơn vị mới (Khoản nằm trong Điều); văn bản khác: cả mục đánh số "1. Xxx"
    head_re = BIG_HEAD_RE if has_dieu else HEAD_RE

    def close() -> None:
        nonlocal cur
        body = [x for x in cur if x[2].strip()]
        if body:
            s, e = body[0][0], body[-1][1]
            kind = "dieu" if DIEU_RE.match(body[0][2].strip()) else "block"
            out.append(_unit(doc_id, doc_type, s, e, kind, text))
        cur = []

    for ln in lines:
        s, e, t = ln
        size = (cur[-1][1] - cur[0][0]) if cur else 0
        is_head = bool(head_re.match(t.strip()))
        is_dieu = bool(DIEU_RE.match(t.strip()))
        if cur and ((is_dieu and size >= 120) or (is_head and size >= lo)):
            close()
        elif cur and size + (e - s) > hi and (KHOAN_RE.match(t.strip()) or t.strip() == "" or size > hi * 1.2):
            close()
        cur.append(ln)
    close()
    return out


# ------------------------------------------------------------------ chọn đơn vị theo kế hoạch (phân tầng, seed cố định)
def compatible(u: dict, qtype: str) -> bool:
    t = u["text"]
    if qtype == "tra_bang":
        return u["kind"] == "table"
    if qtype == "nhieu_doan":
        if u["kind"] == "table":
            return t.count("\n") >= 5
        return len(t) >= 500 and len([1 for ln in t.split("\n") if KHOAN_RE.match(ln.strip()) or re.match(r"^[a-zđ]\)\s", ln.strip())]) >= 2
    if u["kind"] == "table":
        return qtype in ("factoid", "khau_ngu") and u["n_digits"] >= 4
    if qtype == "factoid":
        return u["n_digits"] >= 2
    if qtype in KW:
        return bool(KW[qtype].search(t))
    return True  # khau_ngu


def _overlaps(used: dict[str, list[tuple[int, int]]], u: dict) -> bool:
    return any(not (u["char_end"] <= a or u["char_start"] >= b) for a, b in used.get(u["doc_id"], []))


def split_counts(total: int, types: list[str], khau_ngu_share: float) -> dict[str, int]:
    """Chia `total` câu cho các loại: khau_ngu lấy ~khau_ngu_share, phần còn lại chia đều (dư dồn cho loại đứng trước)."""
    out = {t: 0 for t in types}
    kn = min(total, max(1, round(total * khau_ngu_share))) if "khau_ngu" in types else 0
    rest = [t for t in types if t != "khau_ngu"]
    left = total - kn
    for i, t in enumerate(rest):
        out[t] = left // len(rest) + (1 if i < left % len(rest) else 0)
    if kn:
        out["khau_ngu"] = kn
    return out


def select_units(cfg: dict, docs: dict[str, dict], texts: dict[str, str] | None = None) -> list[dict]:
    """Danh sách đơn vị đã chọn, mỗi đơn vị kèm `qtype` và `group`. Cùng seed + cùng dữ liệu => cùng kết quả."""
    seed, over, ucfg = cfg["seed"], cfg["overgen"], cfg["generation"]
    vlm = vlm_doc_ids()
    pool: dict[str, list[dict]] = {}
    for d, v in sorted(docs.items()):
        g = GROUP_OF.get(v["doc_type"])
        if g is None or g not in cfg["plan"]:
            continue
        text = (texts or {}).get(d) or T.load_doc_text(d)
        for u in extract_units(d, v["doc_type"], text, ucfg):
            u["group"], u["vlm"] = g, d in vlm
            pool.setdefault(g, []).append(u)
    chosen: list[dict] = []
    used: dict[str, list[tuple[int, int]]] = {}
    share = cfg["plan"].get("khau_ngu_share", 0.15)
    for g, pc in cfg["plan"].items():
        if g == "khau_ngu_share":
            continue
        counts = split_counts(pc["total"], pc["types"], share)
        # loại khan hiếm (tra_bang, nhieu_doan) chọn trước để không bị loại khác lấy mất đơn vị
        order = sorted(pc["types"], key=lambda t: (t not in ("tra_bang", "nhieu_doan"), t))
        for qt in order:
            need = math.ceil(counts[qt] * (1 + over))
            cand = [u for u in pool.get(g, []) if compatible(u, qt) and not _overlaps(used, u)]
            need_vlm = math.ceil(pc.get("min_tra_bang_vlm", 0) * (1 + over)) if (g == "ctdt" and qt == "tra_bang") else 0
            picks: list[dict] = []
            for part in ([u for u in cand if u["vlm"]], ) if need_vlm else ():
                picks += _round_robin(part, need_vlm, f"{seed}|{g}|{qt}|vlm", used, 3)
            rest = [u for u in cand if u["unit_id"] not in {p["unit_id"] for p in picks}]
            picks += _round_robin(rest, need - len(picks), f"{seed}|{g}|{qt}", used, 2)
            for u in picks:
                chosen.append({**u, "qtype": qt})
    return chosen


def _round_robin(units: list[dict], n: int, seed_key: str, used: dict, per_doc: int) -> list[dict]:
    if n <= 0:
        return []
    rng = random.Random(seed_key)
    by_doc: dict[str, list[dict]] = {}
    for u in sorted(units, key=lambda x: x["unit_id"]):
        by_doc.setdefault(u["doc_id"], []).append(u)
    for lst in by_doc.values():
        rng.shuffle(lst)
    docs = sorted(by_doc)
    rng.shuffle(docs)
    out: list[dict] = []
    rnd = 0
    while len(out) < n and rnd < per_doc * 50:
        progressed = False
        for d in docs:
            if len(out) >= n:
                break
            lst = by_doc[d]
            while lst and _overlaps(used, lst[-1]):
                lst.pop()
            taken = sum(1 for o in out if o["doc_id"] == d)
            if lst and (taken < per_doc or rnd >= per_doc):
                u = lst.pop()
                out.append(u)
                used.setdefault(u["doc_id"], []).append((u["char_start"], u["char_end"]))
                progressed = True
        rnd += 1
        if not progressed:
            break
    return out


# ------------------------------------------------------------------ prompt
SYSTEM = ("Bạn là sinh viên Trường Đại học Thăng Long đang nhắn tin hỏi phòng Đào tạo. Bạn chỉ dựa vào ĐOẠN TÀI LIỆU được đưa, "
          "tuyệt đối không bịa. Luôn trả về DUY NHẤT một đối tượng JSON hợp lệ.")

COMMON_RULES = """Quy tắc:
1. Viết câu hỏi như sinh viên thật hỏi, tiếng Việt tự nhiên; DIỄN ĐẠT LẠI bằng lời của em, KHÔNG chép nguyên cụm từ dài (từ 6 từ liên tiếp trở lên) của đoạn tài liệu.
2. Câu hỏi phải tự đứng được (không viết "theo đoạn trên", "trong tài liệu này"). Nếu tài liệu chỉ áp dụng cho một học kỳ/năm học/khóa/ngành/hệ cụ thể thì nêu rõ ngay trong câu hỏi để chỉ một tài liệu trả lời được.
3. Câu hỏi PHẢI trả lời được hoàn toàn từ đoạn tài liệu. Không dùng tên người thật; nếu cần nêu tên thì dùng tên giả rõ ràng (Nguyễn Văn A).
4. "quotes": các trích dẫn NGUYÊN VĂN (từng chữ, kể cả dấu và con số) lấy từ đoạn tài liệu, đủ để trả lời; mỗi quote ngắn nhất có thể (một câu, một Khoản, hoặc một dòng bảng); không sửa, không nối, không dùng dấu "..." trong quote.
5. "answer_ref": câu trả lời ngắn gọn, chỉ dựa vào đoạn.
6. "general_knowledge": true nếu người ta có thể trả lời đúng câu này bằng kiến thức chung mà không cần tài liệu, ngược lại false.
Chỉ trả về JSON: {"question": "...", "answer_ref": "...", "quotes": ["..."], "general_knowledge": false}"""

TYPE_RULES = {
    "factoid": "Loại câu hỏi: factoid - hỏi MỘT con số/mức tiền/ngày tháng/số tín chỉ cụ thể có trong đoạn.",
    "dieu_kien": "Loại câu hỏi: điều kiện - hỏi điều kiện/tiêu chí/đối tượng để được làm gì đó.",
    "thu_tuc": "Loại câu hỏi: thủ tục - hỏi hồ sơ cần nộp, các bước thực hiện hoặc nơi nộp.",
    "tra_bang": "Loại câu hỏi: tra bảng - hỏi giá trị của MỘT dòng/ô trong bảng (ví dụ mã học phần, số tín chỉ, tiên quyết, học phí của một ngành, ca thi). Nêu rõ tên dòng cần tra; quote là dòng bảng nguyên văn (dạng | a | b |). Không nhắc tên cột máy móc.",
    "nhieu_doan": "Loại câu hỏi: nhiều đoạn - câu hỏi chỉ trả lời đủ khi kết hợp ÍT NHẤT 2 phần khác nhau của đoạn (2 Khoản, hoặc 2 dòng bảng, hoặc văn bản + dòng bảng). \"quotes\" phải có ít nhất 2 quote ở 2 chỗ khác nhau.",
    "khau_ngu": "Loại câu hỏi: khẩu ngữ - hỏi đời thường như nhắn tin: có thể viết tắt (K38, HK1, TC, CTĐT, ĐKHP, SV), ngắn gọn, thỉnh thoảng thiếu dấu câu; khoảng 1/3 số câu viết KHÔNG DẤU tiếng Việt (ví dụ \"hoc phi ki 1 nam nay bao nhieu\"). Nội dung vẫn phải trả lời được từ đoạn.",
}


def prompt_template(qtype: str) -> str:
    """Mẫu prompt (chưa điền đoạn) - dùng để tính prompt_sha256."""
    return SYSTEM + "\n\n" + TYPE_RULES[qtype] + "\n\n" + COMMON_RULES + "\n\n[TÀI LIỆU: {title}]\n[LOẠI: {doc_type}; {scope}]\n{header}ĐOẠN:\n{unit}"


def render_prompt(unit: dict, doc: dict) -> str:
    scope = []
    if doc.get("khoa_tu") is not None or doc.get("khoa_den") is not None:
        scope.append(f"áp dụng khóa {doc.get('khoa_tu') or '≤'}–{doc.get('khoa_den') or '≥'}")
    if doc.get("nganh"):
        scope.append(f"ngành {doc['nganh']}")
    hdr = f"[HÀNG TIÊU ĐỀ BẢNG (không phải quote): {unit['header']}]\n" if unit.get("header") else ""
    body = prompt_template(unit["qtype"]).split("\n\n", 1)[1]
    for k, v in (("{title}", doc.get("title") or doc.get("doc_heading") or ""), ("{doc_type}", doc["doc_type"]),
                 ("{scope}", "; ".join(scope) or "không giới hạn khóa"), ("{header}", hdr)):
        body = body.replace(k, v)
    return body.replace("{unit}", unit["text"])  # unit thay CUỐI CÙNG: văn bản có thể chứa "{...}"


def prompt_sha(qtype: str) -> str:
    return T.sha256_text(prompt_template(qtype))


# ---- ngoài phạm vi
OOS_HINTS = {
    "khong_lien_quan": ["thời tiết hôm nay ở Hà Nội", "nấu ăn / công thức món ăn", "kết quả bóng đá", "giá vàng và tỉ giá", "viết code Python",
                        "du lịch / đặt vé máy bay", "phim đang chiếu", "sức khỏe / chế độ tập gym", "âm nhạc / ca sĩ nổi tiếng"],
    "cung_linh_vuc": ["học phí của một trường đại học khác (ví dụ Bách khoa Hà Nội)", "điểm chuẩn tuyển sinh năm 2025 của một trường khác",
                      "lịch thi của trường đại học khác", "danh sách giảng viên khoa Y của trường khác", "quy chế đào tạo trình độ tiến sĩ của Đại học Quốc gia",
                      "cách đăng ký ký túc xá của trường khác", "chương trình trao đổi sinh viên ở nước ngoài của trường khác", "lương trung bình ngành CNTT sau tốt nghiệp"],
    "ca_nhan": ["hỏi về kỷ luật/buộc thôi học của một sinh viên cụ thể", "hỏi điểm số/GPA của một sinh viên cụ thể",
                "hỏi số điện thoại/địa chỉ/mã sinh viên của một sinh viên cụ thể", "hỏi học bổng một sinh viên cụ thể đã nhận", "hỏi sinh viên cụ thể đã nợ học phí hay chưa"],
}
OOS_RULES = """Sinh {n} câu hỏi để KIỂM TRA hệ thống hỏi-đáp học vụ của Trường Đại học Thăng Long (hệ thống chỉ có quy chế, học phí, CTĐT, lịch thi, kế hoạch, thông báo, học bổng, quy trình).
Các câu hỏi này hệ thống PHẢI TỪ CHỐI vì {why}. Chủ đề gợi ý: {hint}.
Viết như sinh viên thật nhắn tin, tiếng Việt tự nhiên.{extra}
Chỉ trả về JSON: {{"questions": ["...", "..."]}}"""
OOS_WHY = {"khong_lien_quan": "không liên quan đến học vụ của trường", "cung_linh_vuc": "cùng lĩnh vực giáo dục nhưng thông tin không có trong kho của Trường Đại học Thăng Long",
           "ca_nhan": "hỏi thông tin cá nhân của sinh viên cụ thể (không được tiết lộ)"}
OOS_EXTRA = {"ca_nhan": " BẮT BUỘC dùng tên giả rõ ràng: Nguyễn Văn A, Trần Thị B, Lê Văn C, Phạm Thị D (chỉ những tên này)."}
NHAM_RULES = """Dưới đây là một đoạn tài liệu của trường. Hãy viết MỘT câu hỏi nghe rất gần với nội dung đoạn (cùng chủ đề, cùng thuật ngữ) nhưng hỏi về MỘT ĐIỀU ĐOẠN KHÔNG NÓI
(ví dụ mức khác, đối tượng khác, học kỳ/năm khác, thủ tục khác) nên hệ thống phải từ chối vì thiếu thông tin. Không dùng tên người thật.
[TÀI LIỆU: {title}]
ĐOẠN:
{unit}
Chỉ trả về JSON: {{"questions": ["..."]}}"""

VERSION_RULES = """Dưới đây là CÙNG MỘT nội dung của Quy chế đào tạo đại học Trường Đại học Thăng Long ở 3 phiên bản (áp dụng theo khóa). Các phiên bản có điểm KHÁC NHAU thật sự.
Hãy viết MỘT câu hỏi (như sinh viên hỏi, KHÔNG nêu khóa trong câu hỏi, diễn đạt lại, không chép cụm 6 từ liên tiếp) mà đáp án phụ thuộc phiên bản, và với mỗi phiên bản đưa 1 quote NGUYÊN VĂN (từng chữ, từng con số) trả lời câu hỏi.
Nếu một phiên bản không có nội dung để trả lời thì để quote rỗng "".
{blocks}
Chỉ trả về JSON: {{"question": "...", "answers": {{"2024": {{"quote": "...", "answer": "..."}}, "2025": {{"quote": "...", "answer": "..."}}, "2026": {{"quote": "...", "answer": "..."}}}}}}"""


def prompt_sha_misc(name: str) -> str:
    base = {"oos": OOS_RULES + json.dumps(OOS_WHY, sort_keys=True) + json.dumps(OOS_EXTRA, sort_keys=True), "nham": NHAM_RULES, "version": VERSION_RULES}[name]
    return T.sha256_text(SYSTEM + "\n\n" + base)


# ------------------------------------------------------------------ khác biệt giữa các phiên bản quy chế
def _quy_che_body(text: str) -> str:
    """Phần Quy chế (bỏ Quyết định ban hành): từ lần xuất hiện CUỐI của dòng 'Điều 1.'."""
    ms = [m.start() for m in re.finditer(r"(?m)^Điều\s+1\s*\.", text)]
    return text[ms[-1]:] if ms else text


def _khoan_blocks(text: str) -> list[dict]:
    """Các Khoản (hoặc cả Điều nếu không có Khoản) kèm tiêu đề Điều; tọa độ trong `text` gốc."""
    base = len(text) - len(_quy_che_body(text))
    body = text[base:]
    out: list[dict] = []
    dieu_title, dieu_no, cur = "", "", None
    pos = 0
    for ln in body.split("\n"):
        s = base + pos
        pos += len(ln) + 1
        st = ln.strip()
        m = re.match(r"^Điều\s+(\d+)\s*\.\s*(.*)$", st)
        if m:
            if cur:
                out.append(cur)
            dieu_no, dieu_title = m.group(1), re.sub(r"\s+", " ", m.group(2)).lower()
            cur = {"dieu": dieu_no, "title": dieu_title, "s": s, "e": s + len(ln), "khoan": 0}
            continue
        if KHOAN_RE.match(st) and cur is not None:
            out.append(cur)
            cur = {"dieu": dieu_no, "title": dieu_title, "s": s, "e": s + len(ln), "khoan": int(st.split(".")[0])}
            continue
        if cur is not None and st:
            cur["e"] = s + len(ln)
    if cur:
        out.append(cur)
    for b in out:
        b["text"] = text[b["s"]:b["e"]]
    return out


def _nums(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s))


def find_version_diffs(texts: dict[str, str], pivot: str = "2025", max_n: int = 18) -> list[dict]:
    """So sánh Khoản của các phiên bản: giữ những Khoản mà phiên bản khác có nội dung tương ứng (độ giống >= 0.5) nhưng KHÁC thật
    (khác tập số, hoặc độ giống < 0.9). Ưu tiên khác về số. Trả [{key, blocks: {ver: {s,e,text,doc_id?}}, score, num_diff}]."""
    blocks = {v: _khoan_blocks(t) for v, t in texts.items()}
    cands: list[dict] = []
    for pb in blocks[pivot]:
        if len(pb["text"]) < 60:
            continue
        match: dict[str, dict] = {pivot: pb}
        for v, bl in blocks.items():
            if v == pivot:
                continue
            best, br = None, 0.0
            for b in bl:
                if b["title"][:20] != pb["title"][:20] and difflib.SequenceMatcher(None, b["title"], pb["title"]).ratio() < 0.8:
                    continue
                r = difflib.SequenceMatcher(None, T.norm_text(b["text"]), T.norm_text(pb["text"]), autojunk=False).ratio()
                if r > br:
                    best, br = b, r
            if best is not None and br >= 0.5:
                match[v] = {**best, "ratio": br}
        if len(match) < 2:
            continue
        others = [m for v, m in match.items() if v != pivot]
        num_diff = any(_nums(m["text"]) != _nums(pb["text"]) for m in others)
        low = min(m["ratio"] for m in others)
        if not num_diff and low >= 0.9:
            continue
        cands.append({"key": f"{pb['title'][:40]}#{pb['khoan']}", "blocks": match, "num_diff": num_diff, "min_ratio": round(low, 3), "len": len(pb["text"])})
    cands.sort(key=lambda c: (not c["num_diff"], c["min_ratio"]))
    out, per_dieu = [], Counter()
    for c in cands:
        d = c["blocks"][pivot]["dieu"]
        if per_dieu[d] >= 2 or c["len"] > 1800:
            continue
        per_dieu[d] += 1
        out.append(c)
        if len(out) >= max_n:
            break
    return out


# ------------------------------------------------------------------ kế hoạch lời gọi
def plan_calls(cfg: dict, docs: dict[str, dict], meta: dict) -> list[dict]:
    """Toàn bộ lời gọi LLM (xác định theo seed): mỗi phần tử có call_id duy nhất, kind, prompt đầy đủ, prompt_sha256."""
    calls: list[dict] = []
    for u in select_units(cfg, docs):
        doc = docs[u["doc_id"]]
        calls.append({"call_id": f"gen|{u['unit_id']}|{u['qtype']}", "kind": "gen", "qtype": u["qtype"], "unit": u, "prompt": render_prompt(u, doc),
                      "prompt_sha256": prompt_sha(u["qtype"])})
    oos = cfg["out_of_scope"]
    over = cfg["overgen"]
    for kind in ("khong_lien_quan", "cung_linh_vuc", "ca_nhan"):
        n_target = math.ceil(oos[kind] * (1 + over))
        hints = OOS_HINTS[kind]
        for i in range(n_target):
            hint = hints[i % len(hints)]
            calls.append({"call_id": f"oos|{kind}|{i}", "kind": "oos", "oos_kind": kind, "hint": hint,
                          "prompt": OOS_RULES.format(n=1, why=OOS_WHY[kind], hint=hint, extra=OOS_EXTRA.get(kind, "")), "prompt_sha256": prompt_sha_misc("oos")})
    # câu dễ gây nhầm: đoạn thật (thông báo/hoc_phi/ke_hoach) ngẫu nhiên có seed
    rng = random.Random(f"{cfg['seed']}|nham")
    pool = [u for u in select_units({**cfg, "plan": {"thong_bao": {"total": 10, "types": ["dieu_kien", "thu_tuc"]}, "ke_hoach": {"total": 4, "types": ["factoid"]}}}, docs)]
    rng.shuffle(pool)
    for u in pool[:math.ceil(oos["de_nham"] * (1 + over))]:
        doc = docs[u["doc_id"]]
        calls.append({"call_id": f"nham|{u['unit_id']}", "kind": "nham", "unit": u,
                      "prompt": NHAM_RULES.format(title=doc.get("title") or "", unit=u["text"]), "prompt_sha256": prompt_sha_misc("nham")})
    vers = quy_che_versions(meta)
    if len(vers) == 3:
        texts = {v: T.load_doc_text(d) for v, d in vers.items()}
        need = math.ceil(cfg["version_dependent"]["n_with_khoa"] * (1 + over))
        for c in find_version_diffs(texts, max_n=need)[:need]:
            parts = []
            for v in ("2024", "2025", "2026"):
                b = c["blocks"].get(v)
                parts.append(f"=== PHIÊN BẢN {v} ===\n" + (b["text"] if b else "(không có nội dung tương ứng)"))
            cand = {"key": c["key"], "num_diff": c["num_diff"], "blocks": {v: {"s": b["s"], "e": b["e"], "dieu": b["dieu"]} for v, b in c["blocks"].items()}}
            calls.append({"call_id": f"ver|{c['key']}", "kind": "version", "cand": cand, "prompt": VERSION_RULES.format(blocks="\n\n".join(parts)),
                          "prompt_sha256": prompt_sha_misc("version"), "versions": vers})
    return calls


# ------------------------------------------------------------------ gọi OpenAI
class QuotaExhausted(RuntimeError):
    pass


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def gen_model(cfg: dict) -> str:
    m = cfg["generation"].get("model")
    return m or ((load_config("ocr").get("vlm") or {}).get("openai") or {}).get("model") or ""


class OpenAIChat:
    """Chat Completions theo quy ước vlm_ocr.transcribe_openai (max_completion_tokens). temperature=0; mô hình không nhận temperature thì bỏ và ghi lại."""

    def __init__(self, model: str, temperature: float = 0, max_tokens: int = 1500, sleep=time.sleep, client=None, max_retries: int = 8) -> None:
        self.model, self.temperature, self.max_tokens, self._sleep, self.max_retries = model, temperature, max_tokens, sleep, max_retries
        self.temperature_applied = True
        self._client = client

    def client(self):
        if self._client is None:
            load_env()
            from openai import OpenAI
            self._client = OpenAI(max_retries=0)
        return self._client

    def complete(self, prompt: str) -> tuple[str, dict]:
        import openai
        from rag.embedding.openai_embedder import is_quota_error
        delay = 2.0
        for attempt in range(self.max_retries):
            kw = dict(model=self.model, max_completion_tokens=self.max_tokens, response_format={"type": "json_object"},
                      messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
            if self.temperature_applied:
                kw["temperature"] = self.temperature
            try:
                r = self.client().chat.completions.create(**kw)
                u = r.usage
                return (r.choices[0].message.content or "").strip(), {"input_tokens": getattr(u, "prompt_tokens", None),
                                                                      "output_tokens": getattr(u, "completion_tokens", None)}
            except openai.RateLimitError as e:
                if is_quota_error(e):
                    raise QuotaExhausted(f"{type(e).__name__}: hết quota/credit OpenAI") from None
                self._sleep(delay + random.random())
                delay = min(delay * 2, 60)
            except openai.BadRequestError as e:
                if self.temperature_applied and "temperature" in str(e).lower():
                    self.temperature_applied = False  # mô hình chỉ nhận temperature mặc định: bỏ tham số và ghi vào log
                    continue
                raise
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError):
                self._sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError("Hết số lần thử gọi OpenAI")


def count_tokens(texts: list[str]) -> int:
    try:
        from rag.config import chunking_config
        chunking_config()
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return sum(len(enc.encode(t, disallowed_special=())) for t in texts)
    except Exception:  # noqa: BLE001
        return sum(len(t) // 3 for t in texts)


def dry_run(calls: list[dict], cfg: dict, model: str, done: set[str] | None = None) -> dict:
    """Số lần gọi, token ước tính, chi phí (nếu đã điền giá). KHÔNG gọi API."""
    done = done or set()
    todo = [c for c in calls if c["call_id"] not in done]
    tin = count_tokens([SYSTEM + c["prompt"] for c in todo])
    tout = len(todo) * cfg["generation"]["expected_output_tokens"]
    pr = cfg["generation"]["price_per_1m_tokens"]
    cost = None if pr.get("input") is None or pr.get("output") is None else tin / 1e6 * pr["input"] + tout / 1e6 * pr["output"]
    kinds = Counter(c["kind"] for c in todo)
    return {"model": model, "n_calls": len(todo), "n_done": len(calls) - len(todo), "by_kind": dict(kinds), "input_tokens": tin, "output_tokens": tout,
            "cost_usd": cost}


def read_raw(path: Path) -> list[dict]:
    p = Path(path)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def run_calls(calls: list[dict], chat, raw_path: Path, model: str, cfg: dict, progress=print) -> dict:
    """Gọi LLM cho các lời gọi chưa có trong log thô (ghi NGAY sau mỗi lần gọi => hết quota thì dừng, chạy lại sẽ tiếp tục)."""
    done = {r["call_id"] for r in read_raw(raw_path)}
    max_cost = cfg["generation"].get("max_cost_usd")
    pr = cfg["generation"]["price_per_1m_tokens"]
    spent, n = 0.0, 0
    for c in calls:
        if c["call_id"] in done:
            continue
        try:
            text, usage = chat.complete(c["prompt"])
        except QuotaExhausted as e:
            progress(f"Dừng do hết quota sau {n} lời gọi: {e}")
            return {"stopped": "quota", "n_new": n}
        rec = {"at": T.now(), "call_id": c["call_id"], "kind": c["kind"], "model": model, "prompt_sha256": c["prompt_sha256"], "usage": usage,
               "temperature": chat.temperature if chat.temperature_applied else None, "response": text}
        T.append_log(raw_path, rec)
        n += 1
        if pr.get("input") is not None and usage.get("input_tokens") is not None:
            spent += usage["input_tokens"] / 1e6 * pr["input"] + (usage.get("output_tokens") or 0) / 1e6 * pr["output"]
            if max_cost is not None and spent > max_cost:
                progress(f"Dừng: chi phí {spent:.3f} USD vượt max_cost_usd={max_cost}")
                return {"stopped": "cost", "n_new": n}
        if n % 20 == 0:
            progress(f"  {n} lời gọi...")
    return {"stopped": None, "n_new": n}


# ------------------------------------------------------------------ hậu xử lý
NAME_RE = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-ZĐ][a-zà-ỹ]+(?:\s+[A-ZĐ][a-zà-ỹ]+){1,3}\b")
SAFE_NAMES = ("Thăng Long", "Hà Nội", "Việt Nam", "Nguyễn Văn A", "Trần Thị B", "Lê Văn C", "Phạm Thị D", "Phòng Đào", "Đại Học", "Công Nghệ", "Quản Trị")


def _parse_json(s: str) -> dict | None:
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                v = json.loads(m.group(0))
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _flags_for(question: str) -> list[str]:
    flags = []
    cand = [m.group(0) for m in NAME_RE.finditer(question) if not any(s.lower() in m.group(0).lower() for s in SAFE_NAMES)]
    if cand and not re.search(r"[A-ZĐ]{2,}", question):
        flags.append("co_the_co_ten_rieng")
    return flags


def locate_all(quotes: list[str], doc_id: str, window: tuple[int, int] | None, fuzzy_min: float) -> tuple[list[dict], list[str]]:
    text = T.load_doc_text(doc_id)
    sha = T.sha256_text(text)[:16]
    spans, bad = [], []
    for q in quotes:
        loc = T.locate_quote(text, q, window, fuzzy_min)
        if loc["method"] == "none":
            bad.append(q)
            continue
        s, e = loc["char_start"], loc["char_end"]
        spans.append({"doc_id": doc_id, "char_start": s, "char_end": e, "quote": text[s:e], "locate": loc["method"], "doc_sha256": sha})
    return _dedup_spans(spans), bad


def _dedup_spans(spans: list[dict]) -> list[dict]:
    spans = sorted(spans, key=lambda x: (x["doc_id"], x["char_start"]))
    out: list[dict] = []
    for s in spans:
        if out and out[-1]["doc_id"] == s["doc_id"] and s["char_start"] <= out[-1]["char_end"]:
            continue  # trùng/chồng: giữ span đầu
        out.append(s)
    return out


def build_questions(calls: list[dict], raw: list[dict], cfg: dict, docs: dict[str, dict], existing: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Từ log thô -> (câu hợp lệ [pending], câu bị loại tự động [{call_id, reason, ...}]). Không gọi mạng."""
    ar = cfg["auto_reject"]
    by_call = {c["call_id"]: c for c in calls}
    raws = {r["call_id"]: r for r in raw}
    existing = existing or []
    seen_gen = {(q.get("gen") or {}).get("base_call_id") or (q.get("gen") or {}).get("call_id") for q in existing}
    ok: list[dict] = []
    rejected: list[dict] = []
    ids = list(existing)

    def rej(cid: str, reason: str, **extra) -> None:
        rejected.append({"call_id": cid, "reason": reason, **extra})

    def finalize(q: dict) -> None:
        dup = T.is_duplicate(q["question"], [x["question"] for x in ids if x.get("doc_type") == q.get("doc_type")], ar["dup_ratio"])
        if dup:
            rej(q["gen"]["call_id"], "trung_cau", question=q["question"], trung_voi=dup)
            return
        q["id"] = T.next_id(ids)
        ids.append(q)
        ok.append(q)

    for cid in sorted(by_call):
        c, r = by_call[cid], raws.get(cid)
        if r is None or cid in seen_gen:
            continue
        js = _parse_json(r["response"])
        if js is None:
            rej(cid, "json_loi")
            continue
        base_gen = {"model": r["model"], "prompt_sha256": r["prompt_sha256"], "call_id": cid, "base_call_id": cid, "temperature": r.get("temperature")}
        if c["kind"] == "gen":
            u = c["unit"]
            doc = docs.get(u["doc_id"], {})
            question, quotes = str(js.get("question", "")).strip(), [str(x) for x in (js.get("quotes") or []) if str(x).strip()]
            if not question or not quotes or not js.get("answer_ref"):
                rej(cid, "thieu_truong")
                continue
            if len(question) < 8 or len(question) > 300:
                rej(cid, "do_dai_cau_hoi", question=question)
                continue
            spans, bad = locate_all(quotes, u["doc_id"], (u["char_start"], u["char_end"]), ar["fuzzy_locate_min"])
            if bad or not spans:
                rej(cid, "quote_khong_khop", question=question, quotes=bad or quotes)
                continue
            if c["qtype"] == "nhieu_doan" and len(spans) < 2:
                rej(cid, "it_hon_2_span", question=question)
                continue
            texts = [s["quote"] for s in spans]
            run = T.max_copied_run(question, texts)
            if run >= ar["copy_run_words"]:
                rej(cid, "chep_cum_dai", question=question, run=run)
                continue
            khoa = rep_khoa(doc, cfg) if doc else None
            ctx = {"bac_dao_tao": doc.get("bac_dao_tao", "dai_hoc")}
            if khoa is not None:
                ctx["khoa"] = khoa
            flags = _flags_for(question)
            if js.get("general_knowledge"):
                flags.append("kien_thuc_chung")
            if u.get("vlm"):
                flags.append("ctdt_vlm")
            q = T.new_question(question=question, user_ctx=ctx, type=c["qtype"], doc_type=doc.get("doc_type", u["doc_type"]), expected=spans,
                               answer_ref=str(js["answer_ref"]).strip(), lexical_overlap=T.lexical_overlap(question, texts),
                               lexical_overlap_all=T.lexical_overlap(question, texts, drop_stop=False), flags=flags,
                               gen={**base_gen, "unit": u["unit_id"], "unit_kind": u["kind"]})
            if khoa is not None and doc.get("doc_type") == "quy_che":
                q["version_note"] = f"chỉ đúng với Quy chế {version_of_khoa(khoa)} (K{khoa})"
            finalize(q)
        elif c["kind"] in ("oos", "nham"):
            qs = js.get("questions") or ([js["question"]] if js.get("question") else [])
            qs = [str(x).strip() for x in qs if str(x).strip()]
            if not qs:
                rej(cid, "thieu_truong")
                continue
            question = qs[0]
            kind = c.get("oos_kind", "de_nham")
            if kind == "ca_nhan" and not re.search(r"Nguyễn Văn A|Trần Thị B|Lê Văn C|Phạm Thị D", question):
                rej(cid, "ten_khong_gia", question=question)
                continue
            flags = ["can_chay_thu_retrieval"] + ([] if kind == "ca_nhan" else _flags_for(question))
            extra = {"unit": c["unit"]["unit_id"]} if kind == "de_nham" else {"hint": c.get("hint", "")}
            q = T.new_question(question=question, in_scope=False, expected_behavior="refuse", type="ngoai_pham_vi", doc_type="ngoai_pham_vi",
                               user_ctx={"bac_dao_tao": "dai_hoc"}, expected=[], answer_ref="(từ chối: không có trong kho)", oos_kind=kind, flags=flags,
                               gen={**base_gen, **extra})
            finalize(q)
        elif c["kind"] == "version":
            question = str(js.get("question", "")).strip()
            ans = js.get("answers") or {}
            if not question or not isinstance(ans, dict):
                rej(cid, "thieu_truong")
                continue
            spans: dict[str, dict] = {}
            for ver, doc_id in c["versions"].items():
                a = ans.get(ver) or {}
                qt = str(a.get("quote", "")).strip()
                if not qt:
                    continue
                blk = c["cand"]["blocks"].get(ver)
                win = (blk["s"], blk["e"]) if blk else None
                sp, bad = locate_all([qt], doc_id, win, ar["fuzzy_locate_min"])
                if bad or not sp:
                    rej(cid, "quote_khong_khop", question=question, version=ver, quotes=[qt])
                    spans = {}
                    break
                spans[ver] = {**sp[0], "answer": str(a.get("answer", ""))}
            if len(spans) < 2:
                rej(cid, "it_hon_2_phien_ban", question=question)
                continue
            if T.max_copied_run(question, [s["quote"] for s in spans.values()]) >= ar["copy_run_words"]:
                rej(cid, "chep_cum_dai", question=question)
                continue
            vd = cfg["version_dependent"]
            # (1) một câu CÓ khóa cho mỗi phiên bản có đáp án; (2) một câu KHÔNG khóa (hỏi lại / nhiều phiên bản)
            vers_have = sorted(spans)
            group = f"ver:{c['cand']['key']}"
            vcalls = sorted(k for k in by_call if by_call[k]["kind"] == "version")
            idx = vcalls.index(cid)
            ver = ("2024", "2025", "2026")[idx % 3]  # luân phiên phiên bản để mỗi phiên bản đều có câu có khóa
            if ver not in spans:
                ver = vers_have[idx % len(vers_have)]
            sp = {k: v for k, v in spans[ver].items() if k != "answer"}
            khoa = vd["khoa_by_version"][ver]
            q = T.new_question(question=question, user_ctx={"khoa": khoa, "bac_dao_tao": "dai_hoc"}, type="dieu_kien", doc_type="quy_che", expected=[sp],
                               answer_ref=spans[ver]["answer"], version_note=f"chỉ đúng với Quy chế {ver} (K{khoa})", flags=["phu_thuoc_khoa"],
                               lexical_overlap=T.lexical_overlap(question, [sp["quote"]]), gen={**base_gen, "unit": c["cand"]["key"], "version": ver}, group=group)
            q["gen"]["call_id"] = f"{cid}|{ver}"
            q["id"] = T.next_id(ids)
            ids.append(q)
            ok.append(q)
            if idx >= math.ceil(vd["n_without_khoa"] * (1 + cfg["overgen"])):
                continue  # đủ số câu không-khóa
            allsp = [{k: v for k, v in s.items() if k != "answer"} for _, s in sorted(spans.items())]
            q = T.new_question(question=question, user_ctx={"bac_dao_tao": "dai_hoc"}, expected_behavior="ask_clarify_or_multi_version", type="dieu_kien",
                               doc_type="quy_che", expected=allsp, answer_ref="; ".join(f"K{vd['khoa_by_version'][v]}: {s['answer']}" for v, s in sorted(spans.items())),
                               version_note="nội dung khác nhau giữa các phiên bản Quy chế (không nêu khóa)", flags=["phu_thuoc_khoa", "khong_co_khoa"],
                               lexical_overlap=T.lexical_overlap(question, [s["quote"] for s in allsp]), gen={**base_gen, "unit": c["cand"]["key"]}, group=group)
            q["gen"]["call_id"] = f"{cid}|none"
            q["id"] = T.next_id(ids)
            ids.append(q)
            ok.append(q)
    return ok, rejected


def summarize(ok: list[dict], rejected: list[dict]) -> str:
    lines = [f"Câu hợp lệ (pending): {len(ok)}; loại tự động: {len(rejected)}", "", "Loại tự động theo lý do:"]
    for k, v in Counter(r["reason"] for r in rejected).most_common():
        lines.append(f"  {k}: {v}")
    lines += ["", "doc_type × type (câu hợp lệ):"]
    cnt = Counter((q["doc_type"], q["type"]) for q in ok)
    for (d, t), v in sorted(cnt.items()):
        lines.append(f"  {d:16s} {t:14s} {v}")
    ov = [q["lexical_overlap"] for q in ok if q.get("lexical_overlap") is not None]
    if ov:
        ov.sort()
        q = lambda p: ov[min(len(ov) - 1, int(p * len(ov)))]  # noqa: E731
        lines += ["", f"Độ trùng từ (n={len(ov)}): trung bình {sum(ov) / len(ov):.2f}; p25 {q(.25):.2f}; trung vị {q(.5):.2f}; p75 {q(.75):.2f}; p90 {q(.9):.2f}",
                  "  (cao >0.7 thì kết quả sẽ thiên về BM25; xem phân bố theo khoảng ở trang Tổng kết của UI)"]
    fl = Counter(f for q in ok for f in q.get("flags", []))
    if fl:
        lines += ["", "Cờ cần người duyệt chú ý: " + ", ".join(f"{k}={v}" for k, v in fl.most_common())]
    return "\n".join(lines)

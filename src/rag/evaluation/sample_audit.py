"""Kiểm mẫu độ chính xác OCR của các trang KHÔNG bị gắn cờ (OCR, không có cờ nghi sai).

  python scripts/ingest.py --stage audit-build    # chọn mẫu + dựng ảnh + gói zip gửi người kiểm → data/eval/sample_audit/
  python scripts/ingest.py --stage audit-ui       # mở giao diện kiểm mẫu ngay trên máy này

Cách chọn mẫu (do CHƯƠNG TRÌNH chọn, ngẫu nhiên có kiểm soát, ghi hạt giống để chọn lại đúng như cũ):
  1) Trang: mỗi file lần lượt lấy 1 trang ngẫu nhiên (vòng 1), rồi vòng 2, vòng 3 (tối đa 3 trang/file) cho tới đủ N trang.
  2) Dòng: mỗi trang lấy K dòng ngẫu nhiên, trong đó ưu tiên `num_lines` dòng có số, còn lại là dòng chữ; bỏ dòng quá ngắn.
Người kiểm tra chỉ bấm Accept/Reject; chương trình không điền thay và không sửa data/interim/extract.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rag.config import EVAL_DIR, load_config
from rag.evaluation import audit_ui
from rag.evaluation.extract_eval import load_docs
from rag.evaluation.llm_review import ocr_lines, render_page
from rag.ingestion.corrections_ui import crop_with_context
from rag.ingestion.vlm_ocr import TRIGGER_FLAGS

AUDIT_DIR = EVAL_DIR / "sample_audit"
MIN_CHARS = 10
HAS_NUM = re.compile(r"\d{2,}")


def line_text(ln: list[dict], med: float) -> str:
    """Ghép các khối chữ thành một dòng, giống cách ghép văn bản OCR đã lưu (khoảng trống lớn → ' | ')."""
    s = ""
    for i, w in enumerate(ln):
        if i:
            s += " | " if w["box"][0] - ln[i - 1]["box"][2] > med * 2.5 else " "
        s += w["text"]
    return s


def page_lines(pg: dict) -> list[dict]:
    words = pg["raw"]["words"]
    if not words:
        return []
    heights = sorted(max(1.0, w["box"][3] - w["box"][1]) for w in words)
    med = heights[len(heights) // 2]
    out = []
    for ln in ocr_lines(words):
        t = line_text(ln, med).strip()
        box = [min(w["box"][0] for w in ln), min(w["box"][1] for w in ln), max(w["box"][2] for w in ln), max(w["box"][3] for w in ln)]
        out.append({"text": t, "box": [round(v, 1) for v in box]})
    return out


def eligible_pages(cfg: dict) -> list[tuple[dict, dict]]:
    out = []
    for d in load_docs(cfg):
        for p in d["pages"]:
            if p.get("route") == "ocr" and not p.get("error") and not (TRIGGER_FLAGS & set(p["quality"]["flags"])):
                out.append((d, p))
    return out


def choose_pages(elig: list[tuple[dict, dict]], n: int, per_file: int, rng: random.Random) -> list[tuple[dict, dict]]:
    by_file: dict[str, list] = defaultdict(list)
    for d, p in elig:
        by_file[d["file"]].append((d, p))
    for v in by_file.values():
        rng.shuffle(v)
    files = sorted(by_file)
    rng.shuffle(files)
    chosen = []
    for rnd in range(per_file):
        for f in files:
            if len(chosen) >= n:
                break
            if rnd < len(by_file[f]):
                chosen.append(by_file[f][rnd])
    return chosen


def choose_lines(lines: list[dict], k: int, num_lines: int, rng: random.Random) -> list[tuple[int, dict]]:
    cand = [(i, ln) for i, ln in enumerate(lines) if len(ln["text"]) >= MIN_CHARS]
    nums = [c for c in cand if HAS_NUM.search(c[1]["text"])]
    rest = [c for c in cand if not HAS_NUM.search(c[1]["text"])]
    rng.shuffle(nums)
    rng.shuffle(rest)
    pick = nums[:num_lines] + rest[:k - min(num_lines, len(nums))]
    if len(pick) < k:  # thiếu dòng chữ thì bù thêm dòng số
        used = {i for i, _ in pick}
        pick += [c for c in nums if c[0] not in used][:k - len(pick)]
    return sorted(pick[:k], key=lambda x: x[0])


def build(cfg: dict | None = None, n_pages: int = 80, lines_per_page: int = 6, num_lines: int = 2, per_file: int = 3,
          seed: int = 42, out_dir: Path | None = None) -> dict:
    cfg = cfg or load_config("ocr")
    out_dir = out_dir or AUDIT_DIR
    dpi = cfg.get("render_dpi", 200)
    rng = random.Random(seed)
    elig = eligible_pages(cfg)
    chosen = choose_pages(elig, n_pages, per_file, rng)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "images").mkdir(parents=True)
    pop_lines = pop_nums = 0
    for _, p in elig:  # tỷ lệ dòng có số trong TỔNG THỂ (để báo cáo có trọng số)
        for ln in page_lines(p):
            if len(ln["text"]) >= MIN_CHARS:
                pop_lines += 1
                pop_nums += bool(HAS_NUM.search(ln["text"]))
    pages = []
    for n, (d, p) in enumerate(chosen, 1):
        lines = page_lines(p)
        picks = choose_lines(lines, lines_per_page, num_lines, rng)
        if not picks:
            continue
        img = render_page(d, p, dpi)
        pid = f"p{n:03d}"
        full = img.copy()
        full.thumbnail((1400, 1900))
        full.convert("RGB").save(out_dir / "images" / f"{pid}_full.jpg", quality=80)
        items = []
        for j, (i, ln) in enumerate(picks, 1):
            name = f"images/{pid}_l{j}.jpg"
            crop_with_context(img, ln["box"], min_w=900, min_h=200).convert("RGB").save(out_dir / name, quality=85)
            items.append({"item_id": f"{pid}#{j}", "line_no": i + 1, "total_lines": len(lines), "text": ln["text"],
                          "is_num": bool(HAS_NUM.search(ln["text"])), "img": name})
        pages.append({"page_id": pid, "file": d["file"], "page": p["page"], "full": f"images/{pid}_full.jpg", "items": items})
    sample = {"meta": {"seed": seed, "n_trang": len(pages), "dong_moi_trang": lines_per_page, "dong_so_moi_trang": num_lines,
                       "trang_du_dieu_kien": len(elig), "file_du_dieu_kien": len({d["file"] for d, _ in elig}),
                       "ty_le_dong_so": round(pop_nums / pop_lines, 4) if pop_lines else None,
                       "tao_luc": datetime.now().isoformat(timespec="seconds")}, "pages": pages}
    (out_dir / "sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "index.html").write_text(audit_ui.HTML, encoding="utf-8")
    shutil.copy(Path(audit_ui.__file__), out_dir / "audit_ui.py")
    (out_dir / "chay.py").write_text(RUN_PY, encoding="utf-8")
    (out_dir / "HUONG_DAN.md").write_text(GUIDE, encoding="utf-8")
    zp = out_dir.parent / "sar_kiem_mau.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file() and f.name not in ("state.json", "ket_qua.json", "bao_cao.md"):
                z.write(f, "kiem_mau/" + f.relative_to(out_dir).as_posix())
    return {"trang": len(pages), "dong": sum(len(p["items"]) for p in pages), "trang_du_dieu_kien": len(elig),
            "ty_le_dong_so_tong_the": sample["meta"]["ty_le_dong_so"], "zip": str(zp), "zip_mb": round(zp.stat().st_size / 1e6, 1)}


RUN_PY = '''"""Chạy giao diện kiểm mẫu:  python chay.py   (chỉ cần Python 3.8+, không cài thêm gì)"""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
import audit_ui  # noqa: E402

audit_ui.serve(here, port=8780)
'''

GUIDE = """# Hướng dẫn kiểm mẫu OCR

## Việc cần làm
Bạn kiểm tra xem OCR đọc có đúng không trên một số dòng được chương trình chọn ngẫu nhiên (khoảng 480 dòng, 80 trang,
mỗi trang 6 dòng). Mất khoảng 2-3 giờ. Không cần cài thêm thư viện, không cần Internet, không cần khóa API.

> Tài liệu có thể chứa họ tên, mã sinh viên, số điện thoại. Không đăng lên mạng hay chia sẻ ngoài nhóm.

## Cài đặt (một lần)
1. Cài Python 3.8 trở lên từ https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH").
2. Giải nén file zip, được thư mục `kiem_mau`.
3. Mở PowerShell tại thư mục `kiem_mau` (File Explorer: gõ `powershell` vào thanh địa chỉ rồi Enter).

## Chạy
```
python chay.py
```
Trình duyệt tự mở `http://127.0.0.1:8780/index.html` (chỉ máy bạn truy cập được). Không đóng cửa sổ lệnh khi đang làm;
muốn dừng bấm `Ctrl+C`. Lần sau chạy lại đúng lệnh trên, tiến độ vẫn còn.

## Cách làm
- Mỗi trang có 6 dòng. Mỗi dòng: **ảnh gốc** (khung đỏ là dòng cần kiểm) và **chữ OCR đọc** bên cạnh.
- OCR đọc **đúng** (chữ, dấu, số giống ảnh; bỏ qua khác biệt nhỏ về khoảng trắng): bấm **Accept**.
- OCR đọc **sai** (sai chữ, sai dấu, sai số, thiếu/thừa chữ): bấm **Reject**. Có thể gõ chữ đúng vào ô hiện ra (không bắt buộc).
- Không chắc: bấm vào ảnh hoặc "Xem cả trang" để xem toàn trang. Đừng đoán; nếu thật sự không đọc ra được, ghi lại và hỏi người giao việc.
- Mỗi trang có ô tick "nghi thiếu dòng / bảng vỡ": tick nếu nhìn ảnh cả trang thấy OCR bỏ sót dòng hoặc bảng bị vỡ cấu trúc.
- Thanh trên cùng cho biết đã làm xong bao nhiêu trang. Phải bấm Accept/Reject đủ mọi dòng thì mới Submit được.

## Nộp
Khi hết 80 trang, bấm **Submit**. Giao diện hiện kết quả và ghi hai file `ket_qua.json` và `bao_cao.md` trong thư mục `kiem_mau`.
Gửi **hai file này** cho người giao việc.

## Lỗi thường gặp
- `python` không được nhận ra: cài lại Python và tick "Add python.exe to PATH".
- Trang không mở: chạy lại `python chay.py` (cổng bận thì chương trình tự đổi cổng và in địa chỉ mới).
- Giao diện cũ: nhấn `Ctrl+F5`.
"""

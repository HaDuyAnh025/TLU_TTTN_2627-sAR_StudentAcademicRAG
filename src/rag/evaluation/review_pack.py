"""Gói kiểm tra tay: chọn mẫu theo nhóm → trang web xem ảnh cạnh văn bản OCR → tính tỷ lệ sai từ kết quả NGƯỜI điền.

  python scripts/ingest.py --stage review-pack    # tạo data/eval/review_pack/ (ảnh, index.html, review_sheet.csv, sample_meta.json)
  python scripts/ingest.py --stage review-score   # đọc file CSV đã điền → data/eval/review_score.md

Nguyên tắc: chương trình CHỈ chọn mẫu, hiển thị và tính toán. Các cột đánh giá do người kiểm tra điền;
chương trình không điền, không suy diễn thay. Chỉ đọc data/interim/extract, không sửa gì ở đó.
"""
from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from rag.config import EVAL_DIR, load_config
from rag.evaluation.extract_eval import TRIGGER, load_docs, vn_ratio
from rag.ingestion.loader import FILES_DIR
from rag.ingestion.ocr_engines import load_image_file, render_pdf_page

PACK = EVAL_DIR / "review_pack"
SCORE_MD = EVAL_DIR / "review_score.md"
A_FLAGS = {"number_mismatch", "low_conf", "low_text", "garbled"}

# Cột người kiểm tra điền (để trống khi xuất)
FILL_COLS = ["loi_so_lieu", "loi_chu_dau", "thieu_dong", "sai_thu_tu", "loi_bang", "co_loi_quan_trong", "ghi_chu"]
BASE_COLS = ["id", "nhom", "file", "trang", "tieu_de", "co", "anh", "van_ban_ocr"]

GROUPS = {
    "G1_ocr_khong_co": "OCR, không cờ",
    "G2_ocr_nghi_sai": "OCR, có cờ nghi sai nội dung (number_mismatch/low_conf/low_text/garbled)",
    "G3_ocr_chi_bang": "OCR, chỉ cờ nghi bảng",
    "G4_ocr_chi_dpi": "OCR, chỉ cờ DPI thấp",
    "G5_text_binh_thuong": "Lớp text PDF, tỷ lệ chữ có dấu bình thường",
    "G6_text_nghi_hong": "Lớp text PDF, tỷ lệ chữ có dấu < 0,12 (nghi hỏng hoặc tài liệu tiếng Anh)",
}


def classify(p: dict) -> str | None:
    fl = set(p["quality"]["flags"])
    if p["route"] == "ocr":
        if fl & A_FLAGS:
            return "G2_ocr_nghi_sai"
        if "table_suspected" in fl:
            return "G3_ocr_chi_bang"
        if "low_dpi" in fl:
            return "G4_ocr_chi_dpi"
        return "G1_ocr_khong_co"
    r, n = vn_ratio(p["derived"]["text"])
    if n >= 200 and r < 0.12:
        return "G6_text_nghi_hong"
    return "G5_text_binh_thuong"


def pick(items: list, n: int, per_file: int, rng: random.Random) -> list:
    rng.shuffle(items)
    cnt: dict[str, int] = defaultdict(int)
    out = []
    for it in items:
        if len(out) >= n:
            break
        if cnt[it["file"]] < per_file:
            cnt[it["file"]] += 1
            out.append(it)
    return out


def build_pack(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config("ocr")
    rc = cfg.get("review", {})
    sizes = rc.get("sizes", {"G1_ocr_khong_co": 40, "G2_ocr_nghi_sai": 20, "G3_ocr_chi_bang": 15,
                             "G4_ocr_chi_dpi": 5, "G5_text_binh_thuong": 10, "G6_text_nghi_hong": 10})
    per_file = rc.get("max_pages_per_file", 3)
    dpi = rc.get("image_dpi", 130)
    rng = random.Random(rc.get("seed", 42))
    pop: dict[str, list] = defaultdict(list)
    for d in load_docs(cfg):
        for p in d["pages"]:
            if p.get("error"):
                continue
            g = classify(p)
            pop[g].append({"file": d["file"], "page": p["page"], "doc": d, "p": p})
    meta = {"seed": rc.get("seed", 42), "population": {g: len(pop[g]) for g in GROUPS}, "sample_sizes": {}}
    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "images").mkdir(exist_ok=True)
    rows = []
    for g in GROUPS:
        chosen = pick(list(pop[g]), sizes.get(g, 0), per_file, rng)
        meta["sample_sizes"][g] = len(chosen)
        for it in chosen:
            d, p = it["doc"], it["p"]
            pid = d["file"].rsplit(".", 1)[0] + ("" if p["page"] is None else f"-p{p['page']}")
            safe = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in pid)[:90]
            try:
                path = FILES_DIR / d["file"]
                img = load_image_file(path) if d["file_kind"] == "image" else render_pdf_page(path, p["page"], dpi)
                ang = p["raw"]["orientation"]["angle_ccw"] if p["route"] == "ocr" else 0
                if ang:
                    img = img.rotate(ang, expand=True)
                img.save(PACK / "images" / f"{safe}.jpg", quality=82)
            except Exception as e:  # noqa: BLE001
                print(f"  ! không dựng được ảnh {pid}: {e}")
                continue
            rows.append({"id": safe, "nhom": g, "file": d["file"], "trang": "" if p["page"] is None else p["page"],
                         "tieu_de": (d.get("source") or {}).get("title", ""),
                         "co": ",".join(p["quality"]["flags"]), "anh": f"images/{safe}.jpg",
                         "van_ban_ocr": p["derived"]["text"]})
    rng.shuffle(rows)  # trộn nhóm để người kiểm tra không biết trang thuộc nhóm nào khi đọc (giảm thiên lệch)
    meta["total"] = len(rows)
    (PACK / "sample_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    with (PACK / "review_sheet.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=BASE_COLS + FILL_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r[k] for k in BASE_COLS}, **{c: "" for c in FILL_COLS}})
    (PACK / "index.html").write_text(render_html(rows), encoding="utf-8")
    return meta


# ---------------------------------------------------------------- trang web kiểm tra
def render_html(rows: list[dict]) -> str:
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    return HTML.replace("__DATA__", data).replace("__COLS__", json.dumps(BASE_COLS + FILL_COLS))


HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kiểm tra mẫu OCR</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--mute:#667085;--line:#d9dde3;--acc:#2457d6;--ok:#12794b;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#10141b;--card:#181e28;--ink:#e6e9ef;--mute:#98a2b3;--line:#2b3442;--acc:#7aa2ff;--ok:#4ade80;--bad:#f87171}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
header b{font-size:16px}.pill{background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mute)}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc)}
main{max-width:1500px;margin:0 auto;padding:16px}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:18px;padding:14px}
.item.done{border-color:var(--ok)}
.meta{color:var(--mute);font-size:13px;margin-bottom:8px;word-break:break-all}
.cols{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:14px}
@media (max-width:900px){.cols{grid-template-columns:1fr}}
img{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;max-height:560px;overflow:auto;font:13px/1.45 ui-monospace,Consolas,monospace;margin:0 0 10px}
.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
label{font-size:12px;color:var(--mute);display:block}
input,select,textarea{width:100%;box-sizing:border-box;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit}
.hint{font-size:12px;color:var(--mute);margin:6px 0}
</style></head><body>
<header><b>Kiểm tra mẫu OCR</b><span class="pill" id="prog"></span>
<button id="exp">Xuất CSV</button><button class="sec" id="only">Chỉ hiện trang chưa làm</button>
<span class="pill">Tự lưu tạm trong trình duyệt</span></header>
<main>
<p class="hint">Với mỗi trang: đối chiếu <b>ảnh</b> (trái) với <b>văn bản OCR</b> (phải). Điền số lỗi bạn thấy; <b>để trống nếu chưa xem</b>. Cột "Có lỗi quan trọng" = 1 nếu có lỗi số liệu (tiền, ngày, giờ, mã, số điện thoại), tên riêng, hoặc thiếu/sai nội dung làm đổi nghĩa; 0 nếu không. Nhóm của trang bị ẩn để tránh thiên lệch.</p>
<div id="list"></div></main>
<script>
const DATA=__DATA__, COLS=__COLS__;
const FILL=["loi_so_lieu","loi_chu_dau","thieu_dong","sai_thu_tu","loi_bang","co_loi_quan_trong","ghi_chu"];
const KEY="review_pack_v1:"+DATA.length+":"+(DATA[0]?DATA[0].id:"");
let state={};try{state=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
let onlyTodo=false;
function save(){try{localStorage.setItem(KEY,JSON.stringify(state))}catch(e){}}
function done(r){const s=state[r.id]||{};return s.co_loi_quan_trong===0||s.co_loi_quan_trong===1||s.co_loi_quan_trong==="0"||s.co_loi_quan_trong==="1"}
function prog(){const n=DATA.filter(done).length;document.getElementById("prog").textContent=n+" / "+DATA.length+" trang đã làm"}
function field(r,c,label,type){const v=(state[r.id]||{})[c]??"";
 if(c==="co_loi_quan_trong")return `<div><label>${label}</label><select data-id="${r.id}" data-c="${c}"><option value="">(chưa xem)</option><option value="0"${v==="0"?" selected":""}>0 - không</option><option value="1"${v==="1"?" selected":""}>1 - có</option></select></div>`;
 if(c==="ghi_chu")return `<div style="grid-column:1/-1"><label>${label}</label><textarea rows="2" data-id="${r.id}" data-c="${c}">${v}</textarea></div>`;
 return `<div><label>${label}</label><input type="${type||"number"}" min="0" data-id="${r.id}" data-c="${c}" value="${v}"></div>`}
function esc(s){return String(s).replace(/[&<>]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[m]))}
function render(){const L=document.getElementById("list");L.innerHTML="";
 DATA.forEach((r,i)=>{if(onlyTodo&&done(r))return;
  const d=document.createElement("div");d.className="item"+(done(r)?" done":"");
  d.innerHTML=`<div class="meta"><b>#${i+1}</b> · ${esc(r.file)} · trang ${r.trang===""?"(ảnh)":r.trang} · ${esc(r.tieu_de)}</div>
  <div class="cols"><div><a href="${r.anh}" target="_blank"><img loading="lazy" src="${r.anh}"></a></div>
  <div><pre>${esc(r.van_ban_ocr)||"(không có văn bản)"}</pre><div class="f">
  ${field(r,"loi_so_lieu","Lỗi số liệu (số lượng)")}${field(r,"loi_chu_dau","Từ sai chữ/dấu (số lượng)")}
  ${field(r,"thieu_dong","Dòng thiếu/thừa (số lượng)")}${field(r,"sai_thu_tu","Sai thứ tự đọc (0/1)")}
  ${field(r,"loi_bang","Lỗi bảng (0/1, bỏ trống nếu không có bảng)")}${field(r,"co_loi_quan_trong","Có lỗi quan trọng?")}
  ${field(r,"ghi_chu","Ghi chú")}</div></div></div>`;L.appendChild(d)});
 L.querySelectorAll("[data-id]").forEach(el=>el.addEventListener("input",e=>{const id=el.dataset.id,c=el.dataset.c;
  state[id]=state[id]||{};state[id][c]=el.value;save();prog();const it=el.closest(".item");const r=DATA.find(x=>x.id===id);it.classList.toggle("done",done(r))}));
 prog()}
document.getElementById("only").onclick=()=>{onlyTodo=!onlyTodo;render()};
document.getElementById("exp").onclick=()=>{const q=v=>'"'+String(v??"").replace(/"/g,'""')+'"';
 const lines=[COLS.map(q).join(",")];DATA.forEach(r=>{const s=state[r.id]||{};lines.push(COLS.map(c=>q(FILL.includes(c)?(s[c]??""):r[c])).join(","))});
 const blob=new Blob(["\\ufeff"+lines.join("\\n")],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
 a.href=URL.createObjectURL(blob);a.download="review_sheet_filled.csv";a.click()};
render();
</script></body></html>
"""


# ---------------------------------------------------------------- tính điểm
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def _num(v: str):
    v = (v or "").strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def score(csv_path: str | Path | None = None, out_path: Path | None = None) -> str:
    csv_path = Path(csv_path) if csv_path else PACK / "review_sheet_filled.csv"
    if not csv_path.exists():
        raise SystemExit(f"Chưa có file kết quả đã điền: {csv_path}\n"
                         "Mở data/eval/review_pack/index.html, điền, bấm 'Xuất CSV' rồi lưu file vào đường dẫn trên "
                         "(hoặc truyền --review-csv <đường dẫn>).")
    meta = json.loads((PACK / "sample_meta.json").read_text(encoding="utf-8"))
    pop = meta["population"]
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        v = (r.get("co_loi_quan_trong") or "").strip()
        if v in ("0", "1"):
            by[r["nhom"]].append(r)
    o = ["# Kết quả kiểm tra mẫu tay", "",
         f"_Từ `{csv_path.name}` · {sum(len(v) for v in by.values())}/{len(rows)} trang đã được đánh giá_", "",
         "> Mọi con số đến từ cột **do người kiểm tra điền**. Chương trình chỉ tính toán, không điền hay suy diễn thay. "
         "Khoảng tin cậy là Wilson 95%; mẫu càng nhỏ khoảng càng rộng.", "",
         "## 1. Tỷ lệ trang có lỗi quan trọng theo nhóm", "",
         "| Nhóm | Mô tả | Số trang tổng thể | Đã đánh giá | Trang có lỗi | Tỷ lệ | KTC 95% |", "|---|---|---|---|---|---|---|"]
    est = []
    for g, desc in GROUPS.items():
        rs = by.get(g, [])
        n = len(rs)
        k = sum(1 for r in rs if r["co_loi_quan_trong"].strip() == "1")
        lo, hi = wilson(k, n)
        o.append(f"| `{g}` | {desc} | {pop.get(g, 0)} | {n} | {k} | {k / n * 100:.1f}% | {lo * 100:.0f}%–{hi * 100:.0f}% |"
                 if n else f"| `{g}` | {desc} | {pop.get(g, 0)} | 0 | – | – | – |")
        if n:
            est.append((pop.get(g, 0), k / n, lo, hi, g))
    o.append("")
    ocr = [e for e in est if e[4].startswith("G") and e[4][:2] in ("G1", "G2", "G3", "G4")]
    tot = sum(e[0] for e in ocr)
    if tot and len(ocr) == 4:
        p = sum(e[0] * e[1] for e in ocr) / tot
        lo = sum(e[0] * e[2] for e in ocr) / tot
        hi = sum(e[0] * e[3] for e in ocr) / tot
        o += ["## 2. Ước lượng chung cho toàn bộ trang OCR (ước lượng phân tầng)", "",
              f"- Tỷ lệ trang OCR có lỗi quan trọng: **{p * 100:.1f}%** (khoảng {lo * 100:.0f}%–{hi * 100:.0f}%, xấp xỉ), "
              f"tương đương khoảng {p * tot:.0f}/{tot} trang.", ""]
    g1 = by.get("G1_ocr_khong_co", [])
    if g1:
        k = sum(1 for r in g1 if r["co_loi_quan_trong"].strip() == "1")
        lo, hi = wilson(k, len(g1))
        o += ["## 3. Hệ thống cờ có bỏ sót lỗi không", "",
              f"- Trong nhóm **không cờ**: {k}/{len(g1)} trang có lỗi quan trọng ({lo * 100:.0f}%–{hi * 100:.0f}%). "
              + ("Không thấy lỗi nào trong mẫu: tỷ lệ sai thật của nhóm này không quá khoảng "
                 f"{hi * 100:.0f}% với độ tin cậy 95%." if k == 0 else "Đây là mức lỗi mà hệ thống cờ **không bắt được**."), ""]
    o += ["## 4. Loại lỗi (tổng số theo nhóm, từ các cột bạn điền)", "",
          "| Nhóm | Lỗi số liệu | Từ sai chữ/dấu | Dòng thiếu/thừa | Sai thứ tự (trang) | Lỗi bảng (trang) |", "|---|---|---|---|---|---|"]
    for g in GROUPS:
        rs = by.get(g, [])
        if not rs:
            continue
        s = lambda c: sum(_num(r.get(c, "")) or 0 for r in rs)
        o.append(f"| `{g}` | {s('loi_so_lieu'):.0f} | {s('loi_chu_dau'):.0f} | {s('thieu_dong'):.0f} | {s('sai_thu_tu'):.0f} | {s('loi_bang'):.0f} |")
    o += ["", "## 5. Cách đọc", "",
          "- Nhóm nào có tỷ lệ lỗi cao đáng kể thì nên xử lý (VLM hoặc OCR lại); nhóm có tỷ lệ thấp và khoảng tin cậy hẹp thì có thể giữ nguyên.",
          "- Nếu `G6` (lớp text nghi hỏng) có nhiều lỗi quan trọng, đó là căn cứ để OCR lại nhóm trang này.",
          "- Mẫu chọn tối đa vài trang mỗi file nên các trang cùng file có thể sai giống nhau; kết quả có thể lạc quan hơn thực tế nếu một vài file lỗi nặng chiếm nhiều trang."]
    text = "\n".join(o)
    (out_path or SCORE_MD).write_text(text, encoding="utf-8")
    return text

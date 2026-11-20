"""Giao diện KIỂM MẪU độ chính xác OCR (chỉ dùng thư viện chuẩn của Python, chạy được trên máy không cài gì thêm).

Dữ liệu vào là thư mục có sample.json + images/ (do sample_audit.build tạo). Người kiểm tra xem từng dòng: ảnh gốc | chữ OCR |
Accept (OCR đọc đúng) / Reject (OCR đọc sai). Chương trình KHÔNG điền thay: chưa bấm thì chưa tính. Bấm Submit để tính tỷ lệ
dòng sai kèm khoảng tin cậy 95% (Wilson) rồi ghi ket_qua.json + bao_cao.md vào cùng thư mục.
"""
from __future__ import annotations

import json
import math
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"n": n, "sai": k, "ty_le": round(k / n, 4) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def make_report(sample: dict, state: dict) -> dict:
    """Tính kết quả từ câu trả lời của NGƯỜI (không suy diễn thêm)."""
    ans = state.get("items", {})
    rows = [(it, ans[it["item_id"]]) for pg in sample["pages"] for it in pg["items"] if it["item_id"] in ans]
    num = [r for r in rows if r[0]["is_num"]]
    txt = [r for r in rows if not r[0]["is_num"]]
    rej = lambda xs: sum(1 for _, a in xs if a.get("d") == "reject")  # noqa: E731
    w = sample["meta"].get("ty_le_dong_so")
    rep = {"tong_dong": _rate(rej(rows), len(rows)), "dong_so": _rate(rej(num), len(num)),
           "dong_chu": _rate(rej(txt), len(txt)), "ty_le_dong_so_trong_tong_the": w}
    if w is not None and num and txt:
        rep["uoc_luong_chung_co_trong_so"] = round(w * rej(num) / len(num) + (1 - w) * rej(txt) / len(txt), 4)
    pages_bad = {pg["page_id"] for pg in sample["pages"]
                 if any(ans.get(it["item_id"], {}).get("d") == "reject" for it in pg["items"])}
    flagged = [pid for pid, v in state.get("pages", {}).items() if v.get("thieu_dong")]
    rep["trang"] = {"tong": len(sample["pages"]), "co_it_nhat_1_dong_sai": len(pages_bad),
                    "nghi_thieu_dong_hoac_bang_vo": len(flagged)}
    rep["dong_sai"] = [{"file": pg["file"], "trang": pg["page"], "loai": "so" if it["is_num"] else "chu", "ocr": it["text"],
                        "chu_dung": ans[it["item_id"]].get("dung", "")}
                       for pg in sample["pages"] for it in pg["items"] if ans.get(it["item_id"], {}).get("d") == "reject"]
    hi = rep["tong_dong"]["ci95"][1]
    rep["goi_y"] = ("Tỷ lệ dòng sai thấp và khoảng tin cậy hẹp: có thể chấp nhận các trang không cờ, ghi rõ độ tin cậy."
                    if hi < 0.03 and rep["dong_so"]["sai"] == 0 else
                    "Có lỗi đáng kể (cận trên khoảng tin cậy ≥ 3% hoặc có dòng SỐ sai): nên chạy LLM rà soát cho các trang không cờ "
                    "rồi duyệt bằng giao diện duyệt chỉnh sửa. Đây chỉ là gợi ý; quyết định là của bạn.")
    return rep


def report_md(rep: dict, sample: dict) -> str:
    def row(name, r):
        pct = lambda x: "-" if x is None else f"{x * 100:.1f}%"  # noqa: E731
        return f"| {name} | {r['n']} | {r['sai']} | {pct(r['ty_le'])} | {pct(r['ci95'][0])} – {pct(r['ci95'][1])} |"
    m = sample["meta"]
    out = [f"# Kết quả kiểm mẫu OCR ({datetime.now():%Y-%m-%d %H:%M})", "",
           f"Mẫu: {m['n_trang']} trang, {m['dong_moi_trang']} dòng/trang, hạt giống {m['seed']}, chọn từ {m['trang_du_dieu_kien']} trang "
           f"OCR không cờ ({m['file_du_dieu_kien']} file).", "",
           "| Nhóm | Số dòng | Reject | Tỷ lệ sai | Khoảng tin cậy 95% |", "|---|---|---|---|---|",
           row("Tất cả (gộp, dòng số được lấy nhiều hơn thực tế)", rep["tong_dong"]), row("Dòng có số", rep["dong_so"]),
           row("Dòng chữ", rep["dong_chu"]), ""]
    if "uoc_luong_chung_co_trong_so" in rep:
        out.append(f"Ước lượng chung có trọng số (theo tỷ lệ dòng số {rep['ty_le_dong_so_trong_tong_the']:.0%} của tổng thể): "
                   f"{rep['uoc_luong_chung_co_trong_so'] * 100:.1f}%.")
        out.append("")
    t = rep["trang"]
    out += [f"Trang: {t['co_it_nhat_1_dong_sai']}/{t['tong']} trang có ít nhất 1 dòng Reject; {t['nghi_thieu_dong_hoac_bang_vo']} "
            "trang người kiểm tra đánh dấu nghi thiếu dòng/bảng vỡ.", "",
            "Lưu ý: các dòng cùng một trang không hoàn toàn độc lập nên khoảng tin cậy thực tế hơi rộng hơn con số trên. "
            "Mỗi trang chỉ kiểm một phần dòng, nên kết quả là tỷ lệ DÒNG sai, không phải tỷ lệ trang hoàn toàn sạch.", "",
            f"**Gợi ý:** {rep['goi_y']}", "", "## Các dòng Reject", ""]
    for r in rep["dong_sai"]:
        out.append(f"- [{r['loai']}] {r['file']} tr.{r['trang']}: OCR «{r['ocr']}» → chữ đúng: «{r['chu_dung'] or '(không ghi)'}»")
    return "\n".join(out) + "\n"


def make_handler(d: Path):
    lock = threading.Lock()
    sample = json.loads((d / "sample.json").read_text(encoding="utf-8"))
    sf = d / "state.json"

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(d), **kw)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.split("?")[0] == "/api/state":
                with lock:
                    return self._json(200, json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {})
            super().do_GET()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"ok": False, "loi": "JSON không hợp lệ"})
            with lock:
                if self.path == "/api/save":
                    sf.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    return self._json(200, {"ok": True})
                if self.path == "/api/submit":
                    ans = payload.get("items", {})
                    missing = [it["item_id"] for pg in sample["pages"] for it in pg["items"]
                               if ans.get(it["item_id"], {}).get("d") not in ("accept", "reject")]
                    if missing:
                        return self._json(400, {"ok": False, "con_thieu": len(missing)})
                    rep = make_report(sample, payload)
                    now = datetime.now().isoformat(timespec="seconds")
                    (d / "ket_qua.json").write_text(json.dumps({"nop_luc": now, "tra_loi": payload, "bao_cao": rep},
                                                               ensure_ascii=False, indent=1), encoding="utf-8")
                    (d / "bao_cao.md").write_text(report_md(rep, sample), encoding="utf-8")
                    payload["nop_luc"] = now
                    sf.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    return self._json(200, {"ok": True, "bao_cao": rep})
            self._json(404, {"ok": False})

    return H


def serve(d: Path, port: int = 8780, open_browser: bool = True) -> None:
    d = Path(d)
    (d / "index.html").write_text(HTML, encoding="utf-8")
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(d))
            break
        except OSError:
            continue
    else:
        raise SystemExit("Không mở được cổng nào từ " + str(port))
    url = f"http://127.0.0.1:{p}/index.html"
    print(f"Mở giao diện kiểm mẫu: {url}   (Ctrl+C để dừng)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng.")


HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kiểm mẫu OCR</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--mute:#667085;--line:#d9dde3;--acc:#2457d6;--ok:#12794b;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#10141b;--card:#181e28;--ink:#e6e9ef;--mute:#98a2b3;--line:#2b3442;--acc:#7aa2ff;--ok:#4ade80;--bad:#f87171}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.bar{flex:1;min-width:200px;height:12px;background:var(--line);border-radius:99px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--ok);width:0}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:8px 16px;cursor:pointer;font:inherit}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc)}
button:disabled{opacity:.4;cursor:not-allowed}
button.acc{background:var(--ok);min-width:96px}button.rej{background:var(--bad);min-width:96px}
button.off{background:transparent;color:var(--mute);border:1px solid var(--line)}
main{max-width:1200px;margin:0 auto;padding:12px 16px 80px}
.pg{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:6px 0 10px}
.pill{border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mute)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{text-align:left;font-size:13px;color:var(--mute);padding:8px 10px;border-bottom:1px solid var(--line)}
td{vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}
td.c1{width:44%}td.c2{width:34%}td.c3,td.c4{width:11%;text-align:center}
tr.a td{background:rgba(18,121,75,.08)}tr.r td{background:rgba(180,35,24,.09)}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}
.ocr{font:15px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.tag{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:0 7px;font-size:12px;color:var(--mute);margin-bottom:4px}
textarea{width:100%;box-sizing:border-box;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit;margin-top:6px}
.hint{color:var(--mute);font-size:13px;margin:6px 0}
#rep{display:none;white-space:pre-wrap;background:var(--card);border:1px solid var(--ok);border-radius:10px;padding:14px;margin:12px 0}
#nav{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0 10px}
button.chip{padding:2px 0;min-width:34px;font-size:12px;border-radius:6px}
button.chip.ok{background:var(--ok)}button.chip.todo{background:transparent;color:var(--bad);border:2px solid var(--bad)}
button.chip.cur{outline:3px solid var(--acc);outline-offset:1px}
label.chk{display:flex;gap:6px;align-items:center;cursor:pointer}
@media (max-width:900px){table,thead,tbody,tr,td{display:block;width:auto!important}thead{display:none}td{border:0}}
</style></head><body>
<header><b>Kiểm mẫu OCR</b><div class="bar"><i id="bar"></i></div><span id="prog" class="pill"></span>
<button class="sec" id="prev">← Trang trước</button><button class="sec" id="next">Trang sau →</button>
<button id="submit" disabled>Submit</button></header>
<main>
<p class="hint">Mỗi dòng: so <b>ảnh gốc</b> (khung đỏ là dòng cần kiểm) với <b>chữ OCR đọc</b>. Giống hệt (bỏ qua khác biệt nhỏ về khoảng trắng) thì bấm <b>Accept</b>; sai chữ, sai dấu hoặc sai số thì bấm <b>Reject</b> (có thể gõ chữ đúng, không bắt buộc). Không chắc thì xem ảnh cả trang. Chưa bấm thì chưa tính.</p>
<div id="todo" class="hint"></div><div id="nav"></div><div id="rep"></div>
<div class="pg" id="pg"></div>
<table><thead><tr><th>Tài liệu gốc</th><th>OCR đọc</th><th>Accept</th><th>Reject</th></tr></thead><tbody id="tb"></tbody></table>
</main>
<script>
let S=null,ST={items:{},pages:{}},cur=0,submitted=false;
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function saveSoon(){clearTimeout(window._t);window._t=setTimeout(()=>fetch("/api/save",{method:"POST",body:JSON.stringify(ST)}),400)}
function pageDone(p){return p.items.every(it=>{const a=ST.items[it.item_id];return a&&(a.d==="accept"||a.d==="reject")})}
function prog(){const n=S.pages.length,d=S.pages.filter(pageDone).length;
 document.getElementById("bar").style.width=(100*d/n)+"%";
 document.getElementById("prog").textContent=d+"/"+n+" trang";
 document.getElementById("submit").disabled=(d<n)||submitted;
 document.getElementById("submit").textContent=submitted?"Đã Submit":(d<n?"Submit (còn "+(n-d)+" trang)":"Submit");
 const nv=document.getElementById("nav");nv.innerHTML="";
 S.pages.forEach((p,i)=>{const dn=pageDone(p),k=p.items.filter(it=>{const a=ST.items[it.item_id];return !(a&&(a.d==="accept"||a.d==="reject"))}).length;
  const b=document.createElement("button");b.textContent=i+1;b.title=dn?"Đã xong":"Còn "+k+" dòng chưa bấm";
  b.className="chip"+(dn?" ok":" todo")+(i===cur?" cur":"");b.onclick=()=>{cur=i;draw();window.scrollTo(0,0)};nv.appendChild(b)});
 const t=S.pages.map((p,i)=>[i,p]).filter(x=>!pageDone(x[1]));
 document.getElementById("todo").textContent=t.length?"Trang còn thiếu: "+t.map(x=>(x[0]+1)+" ("+x[1].items.filter(it=>{const a=ST.items[it.item_id];return !(a&&(a.d==="accept"||a.d==="reject"))}).length+" dòng)").join(", "):"Đã đủ mọi dòng."}
function draw(){const p=S.pages[cur];
 document.getElementById("pg").innerHTML='<b>Trang '+(cur+1)+'/'+S.pages.length+'</b><span class="pill">'+esc(p.file)+' · tr.'+(p.page===null?"(ảnh)":p.page)+'</span><a href="'+esc(p.full)+'" target="_blank">Xem cả trang ↗</a>'
  +'<label class="chk"><input type="checkbox" id="miss" '+((ST.pages[p.page_id]||{}).thieu_dong?"checked":"")+'> Trang này nghi thiếu dòng / bảng vỡ (xem ảnh cả trang)</label>';
 document.getElementById("miss").onchange=e=>{ST.pages[p.page_id]={thieu_dong:e.target.checked};saveSoon()};
 const tb=document.getElementById("tb");tb.innerHTML="";
 p.items.forEach(it=>{const a=ST.items[it.item_id]||{};const tr=document.createElement("tr");tr.className=a.d==="accept"?"a":a.d==="reject"?"r":"";
  tr.innerHTML='<td class="c1"><a href="'+esc(p.full)+'" target="_blank"><img loading="lazy" src="'+esc(it.img)+'"></a></td>'
   +'<td class="c2"><span class="tag">'+(it.is_num?"có số":"chữ")+' · dòng '+it.line_no+'/'+it.total_lines+'</span><div class="ocr">'+esc(it.text)+'</div></td>'
   +'<td class="c3"><button class="acc'+(a.d==="accept"?"":" off")+'">Accept</button></td>'
   +'<td class="c4"><button class="rej'+(a.d==="reject"?"":" off")+'">Reject</button>'+(a.d==="reject"?'<textarea rows="2" placeholder="Chữ đúng (không bắt buộc)">'+esc(a.dung||"")+'</textarea>':"")+'</td>';
  tr.querySelector(".acc").onclick=()=>{ST.items[it.item_id]={d:"accept"};saveSoon();draw();prog()};
  tr.querySelector(".rej").onclick=()=>{ST.items[it.item_id]={d:"reject",dung:(a.dung||"")};saveSoon();draw();prog()};
  const ta=tr.querySelector("textarea");if(ta)ta.addEventListener("input",()=>{ST.items[it.item_id]={d:"reject",dung:ta.value};saveSoon()});
  tb.appendChild(tr)});
 document.getElementById("prev").disabled=cur===0;document.getElementById("next").disabled=cur===S.pages.length-1;prog()}
function pct(x){return x==null?"-":(x*100).toFixed(1)+"%"}
function showRep(r){const e=document.getElementById("rep");e.style.display="block";
 const row=(n,x)=>n+": "+x.sai+"/"+x.n+" dòng sai = "+pct(x.ty_le)+" (khoảng tin cậy 95%: "+pct(x.ci95[0])+" – "+pct(x.ci95[1])+")";
 e.textContent="ĐÃ SUBMIT. Kết quả đã ghi vào ket_qua.json và bao_cao.md trong thư mục này (gửi hai file đó cho người giao việc).\n\n"
  +row("Tất cả",r.tong_dong)+"\n"+row("Dòng có số",r.dong_so)+"\n"+row("Dòng chữ",r.dong_chu)+"\nTrang có ≥1 dòng sai: "+r.trang.co_it_nhat_1_dong_sai+"/"+r.trang.tong
  +"; nghi thiếu dòng/bảng vỡ: "+r.trang.nghi_thieu_dong_hoac_bang_vo+"\n\nGợi ý: "+r.goi_y;window.scrollTo(0,0)}
document.getElementById("prev").onclick=()=>{if(cur>0){cur--;draw();window.scrollTo(0,0)}};
document.getElementById("next").onclick=()=>{if(cur<S.pages.length-1){cur++;draw();window.scrollTo(0,0)}};
document.getElementById("submit").onclick=async()=>{
 if(!confirm("Submit kết quả kiểm mẫu? Sau khi Submit sẽ tính tỷ lệ sai."))return;
 const r=await fetch("/api/submit",{method:"POST",body:JSON.stringify(ST)});const j=await r.json();
 if(j.ok){submitted=true;showRep(j.bao_cao);prog()}else alert("Chưa Submit được: còn "+(j.con_thieu||"?")+" dòng chưa bấm Accept/Reject.")};
(async()=>{S=await (await fetch("sample.json")).json();const s=await (await fetch("/api/state")).json();
 if(s.items)ST={items:s.items||{},pages:s.pages||{}};
 if(s.nop_luc){submitted=true}
 cur=Math.max(0,S.pages.findIndex(p=>!pageDone(p)));draw();
 if(submitted){const r=await fetch("ket_qua.json");if(r.ok){showRep((await r.json()).bao_cao)}}})();
</script></body></html>
"""

"""Giao diện DUYỆT câu hỏi đánh giá retrieval (cùng khuôn table_vlm_review_ui: chỉ thư viện chuẩn, http.server, nghe 127.0.0.1).

  python scripts/review_testset.py --reviewer "Tên bạn"                 # mở http://127.0.0.1:8770
  python scripts/review_testset.py --reviewer "Tên bạn" --shard 2/3     # hàng đợi riêng: người thứ 2 trong 3 người

Đọc/ghi data/eval/questions.jsonl (ghi atomic + .bak có timestamp) và nhật ký data/eval/questions_review_log.jsonl.
Nhiều người: mỗi người một bản sao + một --shard khác nhau; sau đó `python scripts/gen_testset.py --merge <file của từng người>`.
Chế độ "Ngoài phạm vi" có nút chạy thử retrieval (hybrid, c2) - cần Qdrant + khóa OpenAI (embedding câu hỏi); không có thì UI báo lỗi, các chức năng khác vẫn chạy.
UI KHÔNG sửa data/processed/, KHÔNG chạy lại chunking/index.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from rag.config import ROOT
from rag.evaluation import testset as T

REJECT_REASONS = {"sai_dap_an": "Đáp án/span sai", "khong_ro": "Câu hỏi mơ hồ/không tự đứng được", "chep_nguyen_van": "Chép nguyên văn tài liệu",
                  "kien_thuc_chung": "Trả lời được bằng kiến thức chung", "trung": "Trùng câu khác", "co_ten_that": "Có tên người thật",
                  "khong_thuc_te": "Sinh viên không hỏi kiểu này", "co_trong_kho": "(Ngoài phạm vi) kho thực sự có câu trả lời", "khac": "Lý do khác"}
TYPES = list(T.TYPES) + ["ngoai_pham_vi"]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "").replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "", s).lower() or "nguoi"


class Store:
    def __init__(self, qpath: Path, log_path: Path, ui_dir: Path, docs_dir: Path | None = None, reviewer: str = "", shard: tuple[int, int] = (1, 1),
                 retriever_factory=None, doc_meta: dict | None = None) -> None:
        self.qpath, self.log_path, self.ui_dir, self.docs_dir = Path(qpath), Path(log_path), Path(ui_dir), docs_dir
        self.reviewer, self.shard = reviewer, shard
        self.lock = threading.RLock()
        self._retriever_factory, self._retriever = retriever_factory, None
        self._meta = doc_meta
        self._mtime = None
        self.rows: list[dict] = []
        self.load()
        self.ui_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- dữ liệu
    def load(self) -> None:
        with self.lock:
            self.rows = T.load_questions(self.qpath)
            self._mtime = self.qpath.stat().st_mtime_ns if self.qpath.exists() else None

    def _fresh(self) -> None:
        cur = self.qpath.stat().st_mtime_ns if self.qpath.exists() else None
        if cur != self._mtime:
            self.load()

    def save(self) -> None:
        T.save_questions(self.rows, self.qpath)
        self._mtime = self.qpath.stat().st_mtime_ns

    def meta(self) -> dict:
        if self._meta is None:
            from rag.evaluation.testset_gen import load_doc_meta
            self._meta = load_doc_meta()
        return self._meta

    def by_id(self, qid: str) -> dict:
        for r in self.rows:
            if r["id"] == qid:
                return r
        raise KeyError(qid)

    def _mine(self, i: int, r: dict) -> bool:
        k, n = self.shard
        return n <= 1 or i % n == k - 1 or r.get("review", {}).get("reviewer") == self.reviewer and r.get("created_by") == "human"

    # ---------------------------------------------------------- hàng đợi
    def queue(self, mode: str = "llm", doc_type: str = "", status: str = "pending") -> list[dict]:
        """mode: llm (câu in_scope do LLM/người viết) | oos (ngoài phạm vi) | all. status: pending|all|<trạng thái>."""
        with self.lock:
            self._fresh()
            out = []
            ordered = sorted(range(len(self.rows)), key=lambda i: self.rows[i]["id"])
            for pos, i in enumerate(ordered):
                r = self.rows[i]
                if not self._mine(pos, r):
                    continue
                oos = r["expected_behavior"] == "refuse"
                if (mode == "oos") != oos and mode != "all":
                    continue
                if doc_type and r["doc_type"] != doc_type:
                    continue
                st = r["review"]["status"]
                if status == "pending" and st not in ("pending", "unsure"):
                    continue
                if status not in ("pending", "all") and st != status:
                    continue
                out.append({"id": r["id"], "question": r["question"][:90], "status": st, "doc_type": r["doc_type"], "type": r["type"],
                            "flags": r.get("flags", []), "created_by": r["created_by"]})
            return out

    def progress(self) -> dict:
        with self.lock:
            mine = [r for pos, r in enumerate(sorted(self.rows, key=lambda r: r["id"])) if self._mine(pos, r)]
            c = Counter(r["review"]["status"] for r in mine)
            return {"total": len(mine), "pending": c["pending"], "unsure": c["unsure"], "done": len(mine) - c["pending"] - c["unsure"], "by_status": dict(c),
                    "doc_types": sorted({r["doc_type"] for r in mine})}

    # ---------------------------------------------------------- văn bản
    def doc_info(self, doc_id: str) -> dict:
        m = self.meta().get(doc_id, {})
        return {"doc_id": doc_id, "title": m.get("title") or m.get("doc_heading") or doc_id, "doc_type": m.get("doc_type", ""), "status": m.get("status", ""),
                "khoa": [m.get("khoa_tu"), m.get("khoa_den")], "in_scope": m.get("in_scope")}

    def doc_slice(self, doc_id: str, start: int, end: int, pad: int = 1800, full: bool = False) -> dict:
        t = T.load_doc_text(doc_id, self.docs_dir)
        lo, hi = (0, len(t)) if full else (max(0, start - pad), min(len(t), end + pad))
        return {**self.doc_info(doc_id), "offset": lo, "total": len(t), "text": t[lo:hi], "sha": T.sha256_text(t)[:16]}

    def docs_list(self, doc_type: str = "", q: str = "", limit: int = 60) -> list[dict]:
        ql = q.lower().strip()
        out = []
        for d, m in self.meta().items():
            if not m.get("in_scope") or m.get("trung_voi"):
                continue
            if doc_type and m.get("doc_type") != doc_type:
                continue
            title = (m.get("title") or m.get("doc_heading") or "")
            if ql and ql not in title.lower() and ql not in d.lower():
                continue
            if not (T.DOCS_DIR / f"{d}.txt").exists() and not (self.docs_dir and Path(self.docs_dir, f"{d}.txt").exists()):
                continue
            out.append({"doc_id": d, "title": title[:120], "doc_type": m.get("doc_type"), "khoa": [m.get("khoa_tu"), m.get("khoa_den")]})
            if len(out) >= limit:
                break
        return out

    def detail(self, qid: str) -> dict:
        with self.lock:
            self._fresh()
            r = self.by_id(qid)
            ex = r.get("expected") or []
            doc = None
            if ex:
                s = min(e["char_start"] for e in ex if e["doc_id"] == ex[0]["doc_id"])
                en = max(e["char_end"] for e in ex if e["doc_id"] == ex[0]["doc_id"])
                doc = self.doc_slice(ex[0]["doc_id"], s, en)
            return {"q": r, "doc": doc, "reasons": REJECT_REASONS, "types": TYPES}

    # ---------------------------------------------------------- thao tác duyệt
    def _log(self, rec: dict) -> None:
        T.append_log(self.log_path, {"time": T.now(), **rec})

    def _apply_fields(self, r: dict, p: dict) -> list[str]:
        changed = []
        if "question" in p and p["question"].strip() != r["question"]:
            r["question"] = p["question"].strip()
            changed.append("question")
        if "answer_ref" in p and p["answer_ref"] != r.get("answer_ref"):
            r["answer_ref"] = p["answer_ref"]
            changed.append("answer_ref")
        if p.get("type") and p["type"] != r["type"]:
            if p["type"] not in TYPES:
                raise ValueError(f"type không hợp lệ: {p['type']}")
            r["type"] = p["type"]
            changed.append("type")
        if "khoa" in p:
            k = p["khoa"]
            ctx = dict(r.get("user_ctx") or {})
            if k in (None, "", 0):
                ctx.pop("khoa", None)
            else:
                ctx["khoa"] = int(k)
            if ctx != r.get("user_ctx"):
                r["user_ctx"] = ctx
                changed.append("user_ctx")
        if "expected" in p:
            new = [T.fix_span(e, self.docs_dir) for e in p["expected"]]
            for e in new:
                if e["char_end"] <= e["char_start"]:
                    raise ValueError("span rỗng")
            old = [(e["doc_id"], e["char_start"], e["char_end"]) for e in (T.fix_span(x, self.docs_dir) for x in r.get("expected") or [])]
            if [(e["doc_id"], e["char_start"], e["char_end"]) for e in new] != old:
                r["expected"] = new
                changed.append("expected")
        if "expected_behavior" in p and p["expected_behavior"] != r["expected_behavior"]:
            if p["expected_behavior"] not in T.BEHAVIORS:
                raise ValueError("expected_behavior không hợp lệ")
            r["expected_behavior"] = p["expected_behavior"]
            r["in_scope"] = p["expected_behavior"] != "refuse"
            changed.append("expected_behavior")
        if changed and r.get("expected"):
            r["lexical_overlap"] = T.recompute_overlap(r, self.docs_dir)
        return changed

    def review(self, qid: str, action: str, reviewer: str, p: dict | None = None) -> dict:
        """action: accept | edit | reject | unsure."""
        p = p or {}
        if not reviewer:
            raise ValueError("chưa nhập tên người duyệt")
        if action not in ("accept", "edit", "reject", "unsure"):
            raise ValueError("action không hợp lệ")
        with self.lock:
            self._fresh()
            r = self.by_id(qid)
            changed = self._apply_fields(r, p) if action in ("accept", "edit") else []
            if action in ("accept", "edit"):
                if r["expected_behavior"] in ("answer",) and not r.get("expected"):
                    raise ValueError("câu cần trả lời phải có ít nhất 1 span đáp án")
                if r["type"] == "nhieu_doan" and len(r.get("expected") or []) < 2:
                    raise ValueError("loại nhieu_doan cần >= 2 span")
                if "kien_thuc_chung" in r.get("flags", []) and p.get("xac_nhan_kien_thuc_chung") is None and action == "accept":
                    raise ValueError("LLM đánh dấu 'trả lời được bằng kiến thức chung': tích xác nhận (không phải kiến thức chung) rồi mới chấp nhận, hoặc Loại")
                if "co_the_co_ten_rieng" in r.get("flags", []) and p.get("xac_nhan_ten") is None and action == "accept":
                    raise ValueError("Câu có thể chứa tên riêng: tích xác nhận không có tên người thật")
            status = {"accept": "accepted", "edit": "edited", "reject": "rejected", "unsure": "unsure"}[action]
            if action == "accept" and changed:
                status = "edited"
            note = (p.get("note") or "")
            if action == "reject":
                reason = p.get("reason") or "khac"
                if reason not in REJECT_REASONS:
                    raise ValueError("lý do loại không hợp lệ")
                note = (reason + (": " + note if note else ""))
            r["review"] = {"status": status, "reviewer": reviewer, "time": T.now(), "note": note}
            if status in ("accepted", "edited"):
                r["flags"] = [f for f in r.get("flags", []) if f not in ("kien_thuc_chung", "co_the_co_ten_rieng")] if (p.get("xac_nhan_kien_thuc_chung") or p.get("xac_nhan_ten")) else r.get("flags", [])
            self.save()
            self._log({"reviewer": reviewer, "id": qid, "action": action, "status": status, "changed": changed, "note": note})
            return {"ok": True, "status": status, "changed": changed}

    def add_human(self, reviewer: str, p: dict) -> dict:
        if not reviewer:
            raise ValueError("chưa nhập tên người duyệt")
        question = (p.get("question") or "").strip()
        if len(question) < 6:
            raise ValueError("chưa nhập câu hỏi")
        beh = p.get("expected_behavior") or "answer"
        spans = [T.fix_span(e, self.docs_dir) for e in p.get("expected") or []]
        if beh == "answer" and not spans:
            raise ValueError("chọn ít nhất 1 span đáp án trên văn bản")
        if beh == "answer" and not (p.get("answer_ref") or "").strip():
            raise ValueError("chưa nhập câu trả lời")
        ctx = {"bac_dao_tao": "dai_hoc"}
        if p.get("khoa") not in (None, "", 0):
            ctx["khoa"] = int(p["khoa"])
        dt = p.get("doc_type") or (self.meta().get(spans[0]["doc_id"], {}).get("doc_type") if spans else "ngoai_pham_vi")
        with self.lock:
            self._fresh()
            prefix = f"qh_{slug(reviewer)}_"
            n = 1 + max([int(m.group(1)) for r in self.rows if (m := re.fullmatch(rf"{re.escape(prefix)}(\d+)", r["id"]))] or [0])
            q = T.new_question(id=f"{prefix}{n:03d}", question=question, user_ctx=ctx, in_scope=beh != "refuse", expected_behavior=beh,
                               type=p.get("type") or "khau_ngu", doc_type=dt, expected=spans if beh != "refuse" else [],
                               answer_ref=p.get("answer_ref", ""), created_by="human", gen={"model": "", "prompt_sha256": "", "unit": ""},
                               review={"status": "accepted", "reviewer": reviewer, "time": T.now(), "note": "câu do người viết"}, flags=["nguoi_viet"])
            if beh == "refuse":
                q["oos_kind"], q["type"], q["doc_type"] = p.get("oos_kind") or "khong_lien_quan", "ngoai_pham_vi", "ngoai_pham_vi"
            if spans:
                q["lexical_overlap"] = T.recompute_overlap(q, self.docs_dir)
            self.rows.append(q)
            self.save()
            self._log({"reviewer": reviewer, "id": q["id"], "action": "add_human", "status": "accepted"})
            return {"ok": True, "id": q["id"], "lexical_overlap": q.get("lexical_overlap")}

    # ---------------------------------------------------------- chạy thử retrieval (ngoài phạm vi)
    def probe(self, question: str, user_ctx: dict | None = None, config: str = "c2") -> dict:
        try:
            if self._retriever is None:
                if self._retriever_factory is not None:
                    self._retriever = self._retriever_factory()
                else:
                    from rag.retrieval.retriever import Retriever
                    self._retriever = Retriever()
            res = self._retriever.retrieve(question, config, "hybrid", user_ctx or {"bac_dao_tao": "dai_hoc"})
        except Exception as e:  # noqa: BLE001 - UI phải sống khi Qdrant/khóa API không có
            return {"ok": False, "loi": f"{type(e).__name__}: {e}"}
        top = []
        for c in res.final:
            pl = c["payload"]
            top.append({"rank": len(top) + 1, "chunk_id": c["chunk_id"], "doc_id": pl["doc_id"], "score": round(float(c.get("final_score", 0)), 4),
                        "breadcrumb": pl["embed_text"][:140], "snippet": (pl.get("content") or "")[:300],
                        "char_start": pl.get("char_start"), "char_end": pl.get("char_end")})
        return {"ok": True, "top": top, "timings": res.timings}

    # ---------------------------------------------------------- tổng kết
    def summary(self) -> dict:
        with self.lock:
            self._fresh()
            rows = self.rows
            st = Counter(r["review"]["status"] for r in rows)
            matrix: dict = {}
            for r in rows:
                matrix.setdefault(r["doc_type"], Counter())[r["review"]["status"]] += 1
            kept = [r for r in rows if r["review"]["status"] in T.SCORED]
            tt: dict = {}
            for r in kept:
                tt.setdefault(r["doc_type"], Counter())[r["type"]] += 1
            hist = Counter()
            for r in rows:
                if r["review"]["status"] != "rejected" and r.get("lexical_overlap") is not None:
                    hist[min(9, int(r["lexical_overlap"] * 10))] += 1
            vals = sorted(r["lexical_overlap"] for r in kept if r.get("lexical_overlap") is not None)
            return {"total": len(rows), "by_status": dict(st), "status_x_doctype": {k: dict(v) for k, v in sorted(matrix.items())},
                    "type_x_doctype_accepted": {k: dict(v) for k, v in sorted(tt.items())},
                    "overlap_hist": [hist.get(i, 0) for i in range(10)],
                    "overlap_mean": round(sum(vals) / len(vals), 3) if vals else None, "overlap_median": vals[len(vals) // 2] if vals else None,
                    "split": dict(Counter(r.get("split") or "-" for r in kept)),
                    "behavior": dict(Counter(r["expected_behavior"] for r in kept)),
                    "created_by": dict(Counter(r["created_by"] for r in kept)),
                    "khoa_phu_thuoc": sum(1 for r in kept if "phu_thuoc_khoa" in r.get("flags", []) and r["expected_behavior"] == "answer"),
                    "human": sum(1 for r in kept if r["created_by"] == "human"),
                    "reviewers": dict(Counter(r["review"]["reviewer"] for r in rows if r["review"]["status"] != "pending"))}

    def summary_md(self) -> str:
        s = self.summary()
        L = [f"# Tổng kết bộ câu hỏi ({T.now()})", "", f"Tổng {s['total']} câu; theo trạng thái: {s['by_status']}", "",
             "## Trạng thái × doc_type", "", "| doc_type | " + " | ".join(T.STATUSES) + " |", "|---|" + "---|" * len(T.STATUSES)]
        for d, c in s["status_x_doctype"].items():
            L.append(f"| {d} | " + " | ".join(str(c.get(x, 0)) for x in T.STATUSES) + " |")
        L += ["", "## Câu đã chấp nhận: type × doc_type", "", "| doc_type | " + " | ".join(TYPES) + " |", "|---|" + "---|" * len(TYPES)]
        for d, c in s["type_x_doctype_accepted"].items():
            L.append(f"| {d} | " + " | ".join(str(c.get(x, 0)) for x in TYPES) + " |")
        L += ["", f"## Độ trùng từ (câu chưa bị loại): trung bình {s['overlap_mean']}, trung vị {s['overlap_median']}", "",
              "| khoảng | số câu |", "|---|---|"] + [f"| {i / 10:.1f}–{(i + 1) / 10:.1f} | {n} |" for i, n in enumerate(s["overlap_hist"])]
        L += ["", f"Split (câu đã chấp nhận): {s['split']}; hành vi: {s['behavior']}; người viết: {s['human']}; phụ thuộc khóa (answer): {s['khoa_phu_thuoc']}",
              "", "Tập test CHỈ chạy cuối để báo cáo; KHÔNG chỉnh tham số trên test."]
        return "\n".join(L)

    def export_summary(self) -> Path:
        p = self.qpath.with_name("questions_summary.md")
        p.write_text(self.summary_md(), encoding="utf-8")
        return p


# ------------------------------------------------------------------ HTTP
def make_handler(store: Store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            path, q = unquote(u.path), parse_qs(u.query)
            g = lambda k, d="": q.get(k, [d])[0]  # noqa: E731
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                if path == "/api/state":
                    return self._json(200, {"reviewer": store.reviewer, "progress": store.progress(), "types": TYPES, "reasons": REJECT_REASONS,
                                            "doc_types": sorted({m.get("doc_type") for m in store.meta().values() if m.get("in_scope")})})
                if path == "/api/queue":
                    return self._json(200, {"items": store.queue(g("mode", "llm"), g("doc_type"), g("status", "pending")), "progress": store.progress()})
                if path == "/api/q":
                    return self._json(200, store.detail(g("id")))
                if path == "/api/doc":
                    return self._json(200, store.doc_slice(g("doc_id"), int(g("start", "0")), int(g("end", "0")), int(g("pad", "1800")), g("full") == "1"))
                if path == "/api/docs":
                    return self._json(200, store.docs_list(g("doc_type"), g("q")))
                if path == "/api/summary":
                    return self._json(200, store.summary())
            except (KeyError, FileNotFoundError, ValueError) as e:
                return self._json(404, {"ok": False, "loi": f"{type(e).__name__}: {e}"})
            self._json(404, {"ok": False})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            try:
                p = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"ok": False, "loi": "JSON không hợp lệ"})
            who = (p.get("reviewer") or store.reviewer or "").strip()
            try:
                if self.path == "/api/user":
                    store.reviewer = who
                    return self._json(200, {"ok": True})
                if self.path == "/api/review":
                    return self._json(200, store.review(p["id"], p["action"], who, p))
                if self.path == "/api/add":
                    return self._json(200, store.add_human(who, p))
                if self.path == "/api/probe":
                    return self._json(200, store.probe(p["question"], p.get("user_ctx")))
                if self.path == "/api/summary/export":
                    return self._json(200, {"ok": True, "file": str(store.export_summary())})
            except (KeyError, ValueError, FileNotFoundError) as e:
                return self._json(400, {"ok": False, "loi": f"{type(e).__name__}: {e}"})
            self._json(404, {"ok": False})

    return H


def serve(store: Store, port: int = 8770, open_browser: bool = True) -> None:
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(store))
            break
        except OSError:
            continue
    else:
        raise SystemExit(f"Không mở được cổng nào từ {port}")
    url = f"http://127.0.0.1:{p}/"
    pr = store.progress()
    print(f"{pr['total']} câu trong hàng đợi của bạn ({pr['pending']} chưa duyệt). Mở: {url}   (Ctrl+C để dừng)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng.")


def default_store(reviewer: str = "", shard: tuple[int, int] = (1, 1), qpath: Path | None = None) -> Store:
    cfg = T.testset_config()
    return Store(qpath or cfg["paths"]["questions"], cfg["paths"]["review_log"], ROOT / "data" / "eval" / "testset_ui", reviewer=reviewer, shard=shard)


HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Duyệt câu hỏi đánh giá</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--bd:#d9dde3;--tx:#1d2330;--mut:#667085;--pri:#1f6feb;--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,Segoe UI,Arial;background:var(--bg);color:var(--tx)}
header{display:flex;gap:12px;align-items:center;padding:8px 14px;background:#fff;border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:5;flex-wrap:wrap}
header h1{font-size:15px;margin:0}nav button{border:1px solid var(--bd);background:#fff;padding:5px 10px;border-radius:6px;cursor:pointer}nav button.on{background:var(--pri);color:#fff;border-color:var(--pri)}
input,select,textarea{font:inherit;border:1px solid var(--bd);border-radius:6px;padding:5px 7px;background:#fff}textarea{width:100%;resize:vertical}
button.b{border:1px solid var(--bd);background:#fff;padding:6px 12px;border-radius:6px;cursor:pointer}button.b:hover{background:#eef2f7}
button.ok{background:var(--ok);color:#fff;border-color:var(--ok)}button.bad{background:var(--bad);color:#fff;border-color:var(--bad)}button.pri{background:var(--pri);color:#fff;border-color:var(--pri)}
main{display:grid;grid-template-columns:330px 1fr;gap:12px;padding:12px}#side{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:8px;max-height:calc(100vh - 90px);overflow:auto}
#list .it{padding:6px;border-bottom:1px solid #eef0f3;cursor:pointer;font-size:13px}#list .it.on{background:#e8f0fe}#list .it small{color:var(--mut)}
.badge{display:inline-block;border-radius:10px;padding:0 7px;font-size:11px;margin-right:4px;background:#eef0f3}.badge.accepted,.badge.edited{background:#dafbe1;color:var(--ok)}.badge.rejected{background:#ffebe9;color:var(--bad)}.badge.unsure{background:#fff8c5;color:var(--warn)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:10px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}
.chip{background:#eef0f3;border-radius:5px;padding:1px 7px;font-size:12px}.chip.w{background:#fff8c5;color:var(--warn)}.chip.r{background:#ffebe9;color:var(--bad)}
#doc{white-space:pre-wrap;font:13px/1.55 Consolas,Menlo,monospace;max-height:56vh;overflow:auto;border:1px solid var(--bd);border-radius:6px;padding:8px;background:#fcfcfd;user-select:text}
mark.sp{background:#ffe08a}mark.sel{background:#9fd3ff}mark.cur{background:#ffd166;outline:2px solid #e0a800}.spanrow{border:1px solid var(--bd);border-radius:6px;padding:4px 8px;margin:4px 0;font-size:12px;display:flex;gap:6px;align-items:flex-start}
.spanrow q{flex:1;color:#333}.hint{color:var(--mut);font-size:12px}.err{color:var(--bad)}.okmsg{color:var(--ok)}
table{border-collapse:collapse}td,th{border:1px solid var(--bd);padding:3px 8px;text-align:right}th:first-child,td:first-child{text-align:left}
.probe{border-left:3px solid var(--pri);padding-left:8px;margin:4px 0;font-size:12px}kbd{background:#eee;border:1px solid #ccc;border-radius:3px;padding:0 4px;font-size:11px}
</style></head><body>
<header><h1>Duyệt câu hỏi đánh giá</h1>
<nav><button id="t_llm" class="on">Duyệt câu</button><button id="t_oos">Ngoài phạm vi</button><button id="t_add">Thêm câu người viết</button><button id="t_sum">Tổng kết</button></nav>
<span>Người duyệt: <input id="who" size="16" placeholder="tên của bạn"></span><span id="prog" class="hint"></span><span class="hint">Phím: <kbd>A</kbd> chấp nhận <kbd>E</kbd> lưu sửa <kbd>R</kbd> loại <kbd>U</kbd> không chắc <kbd>J</kbd>/<kbd>K</kbd> sau/trước</span>
<span id="msg"></span></header>
<main id="m">
<aside id="side"><div class="row"><select id="f_dt"><option value="">mọi doc_type</option></select><select id="f_st"><option value="pending">chưa duyệt</option><option value="all">tất cả</option><option value="accepted">accepted</option><option value="edited">edited</option><option value="rejected">rejected</option><option value="unsure">unsure</option></select></div><div id="list"></div></aside>
<section id="main"></section></main>
<script>
const $=id=>document.getElementById(id);let mode='llm',items=[],idx=-1,cur=null,docv=null,sel=null,repl=-1,state={};
async function api(p,b){const r=await fetch(p,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:{});let j;try{j=await r.json()}catch(e){j={ok:false,loi:'lỗi máy chủ'}}return j}
function flash(t,bad){const m=$('msg');m.textContent=t;m.className=bad?'err':'okmsg';setTimeout(()=>{if(m.textContent===t)m.textContent=''},6000)}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function init(){state=await api('/api/state');$('who').value=localStorage.getItem('who')||state.reviewer||'';if($('who').value)api('/api/user',{reviewer:$('who').value});
 for(const d of state.doc_types)$('f_dt').insertAdjacentHTML('beforeend',`<option>${esc(d)}</option>`);setMode('llm')}
$('who').onchange=()=>{localStorage.setItem('who',$('who').value);api('/api/user',{reviewer:$('who').value})};
for(const m of ['llm','oos','add','sum'])$('t_'+m).onclick=()=>setMode(m);$('f_dt').onchange=$('f_st').onchange=()=>loadQueue();
async function setMode(m){mode=m;for(const x of ['llm','oos','add','sum'])$('t_'+x).classList.toggle('on',x===m);
 $('side').style.display=(m==='llm'||m==='oos')?'':'none';$('m').style.gridTemplateColumns=(m==='llm'||m==='oos')?'330px 1fr':'1fr';
 if(m==='llm'||m==='oos')await loadQueue();else if(m==='add')viewAdd();else viewSum()}
async function loadQueue(keep){const r=await api(`/api/queue?mode=${mode}&doc_type=${encodeURIComponent($('f_dt').value)}&status=${$('f_st').value}`);items=r.items;const p=r.progress;
 $('prog').textContent=`Của bạn: ${p.done}/${p.total} đã duyệt, ${p.pending} chưa, ${p.unsure} không chắc`;
 $('list').innerHTML=items.map((it,i)=>`<div class="it" data-i="${i}"><span class="badge ${it.status}">${it.status}</span><span class="badge">${esc(it.doc_type)}/${esc(it.type)}</span>${it.flags.length?'<span class="chip w">!</span>':''}<br>${esc(it.question)}</div>`).join('')||'<p class="hint">Hàng đợi trống.</p>';
 for(const e of $('list').querySelectorAll('.it'))e.onclick=()=>openIdx(+e.dataset.i);
 if(items.length)openIdx(keep!=null?Math.min(keep,items.length-1):0);else{cur=null;$('main').innerHTML='<div class="card">Không còn câu nào trong bộ lọc này.</div>'}}
async function openIdx(i){idx=i;for(const e of $('list').querySelectorAll('.it'))e.classList.toggle('on',+e.dataset.i===i);const e=$('list').querySelector(`.it[data-i="${i}"]`);if(e)e.scrollIntoView({block:'nearest'});
 const d=await api('/api/q?id='+items[i].id);cur=d.q;docv=d.doc;sel=null;repl=-1;viewQ(d)}
function overlapChip(v){if(v==null)return'';const c=v>0.7?'r':v>0.5?'w':'';return `<span class="chip ${c}" title="tỉ lệ token câu hỏi có trong span">trùng từ ${v}</span>`}
function viewQ(d){const q=cur;const oos=q.expected_behavior==='refuse';
 $('main').innerHTML=`<div class="card"><div class="row"><b>${esc(q.id)}</b><span class="badge ${q.review.status}">${q.review.status}</span><span class="chip">${esc(q.doc_type)}</span><span class="chip">${esc(q.expected_behavior)}</span>
 ${q.split?`<span class="chip">${q.split}</span>`:''}${overlapChip(q.lexical_overlap)}${q.version_note?`<span class="chip w">${esc(q.version_note)}</span>`:''}${(q.flags||[]).map(f=>`<span class="chip w">${esc(f)}</span>`).join('')}<span class="hint">${esc(q.created_by)} · ${esc((q.gen||{}).model||'')}</span></div>
 <div class="hint">Câu hỏi</div><textarea id="q_q" rows="2">${esc(q.question)}</textarea>
 ${oos?'':`<div class="hint">Câu trả lời tham chiếu</div><textarea id="q_a" rows="2">${esc(q.answer_ref)}</textarea>`}
 <div class="row">Loại <select id="q_t">${d.types.map(t=>`<option ${t===q.type?'selected':''}>${t}</option>`).join('')}</select> Khóa (user_ctx) <input id="q_k" size="3" value="${q.user_ctx&&q.user_ctx.khoa||''}">
 Hành vi <select id="q_b">${['answer','refuse','ask_clarify_or_multi_version'].map(t=>`<option ${t===q.expected_behavior?'selected':''}>${t}</option>`).join('')}</select>${q.oos_kind?`<span class="chip">${esc(q.oos_kind)}</span>`:''}</div>
 ${oos?probeUI():spansUI()}
 <div class="row">${(q.flags||[]).includes('kien_thuc_chung')?'<label><input type="checkbox" id="x_kt"> xác nhận KHÔNG phải kiến thức chung</label>':''}${(q.flags||[]).includes('co_the_co_ten_rieng')?'<label><input type="checkbox" id="x_ten"> xác nhận không có tên người thật</label>':''}</div>
 <div class="row"><button class="b ok" id="a_ok">Chấp nhận (A)</button><button class="b pri" id="a_ed">Lưu bản sửa (E)</button><select id="rs">${Object.entries(d.reasons).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('')}</select><button class="b bad" id="a_rj">Loại (R)</button><button class="b" id="a_un">Không chắc (U)</button>
 <input id="note" size="30" placeholder="ghi chú" value="${esc(q.review.note||'')}"><button class="b" id="a_pv">◀ K</button><button class="b" id="a_nx">J ▶</button></div></div>
 ${oos?'':`<div class="card"><div class="row"><b id="dtitle"></b><span class="hint" id="dinfo"></span><button class="b" id="d_more">Mở rộng ±</button><button class="b" id="d_full">Toàn văn</button></div>
 <div class="hint">Kéo chuột chọn đoạn trên văn bản, rồi bấm nút bên dưới.</div><div id="doc"></div></div>`}`;
 $('a_ok').onclick=()=>act('accept');$('a_ed').onclick=()=>act('edit');$('a_rj').onclick=()=>act('reject');$('a_un').onclick=()=>act('unsure');$('a_nx').onclick=()=>go(1);$('a_pv').onclick=()=>go(-1);
 if(oos){$('pr').onclick=probe}else{drawDoc();bindSel()}}
function spansUI(){const ex=cur.expected||[];return `<div class="hint">Span đáp án (${ex.length})</div><div id="spans">${ex.map((e,i)=>spanRow(e,i)).join('')||'<span class="err">chưa có span</span>'}</div>
 <div class="row"><button class="b" id="s_add">+ Thêm vùng chọn làm span mới</button><button class="b" id="s_rep" disabled>Thay span đang chọn bằng vùng chọn</button><span id="selinfo" class="hint">chưa chọn vùng</span></div>`}
function spanRow(e,i){return `<div class="spanrow" data-i="${i}"><b>#${i+1}</b><span>${esc(e.doc_id.slice(0,14))} [${e.char_start}-${e.char_end}]</span><q>${esc((e.quote||'').slice(0,220))}</q><button class="b" onclick="pickSpan(${i})">chọn</button><button class="b" onclick="delSpan(${i})">xóa</button></div>`}
window.pickSpan=i=>{repl=i;$('s_rep').disabled=!sel;$('selinfo').textContent=`đang chọn span #${i+1}`+(sel?`; vùng chọn [${sel.s}-${sel.e}]`:'');drawDoc();const m=document.querySelector('mark.cur');if(m)m.scrollIntoView({block:'center'})};
window.delSpan=i=>{cur.expected.splice(i,1);repl=-1;refreshSpans()};
function refreshSpans(){$('spans').innerHTML=cur.expected.map((e,i)=>spanRow(e,i)).join('')||'<span class="err">chưa có span</span>';drawDoc();bindSpanBtns()}
function bindSpanBtns(){if($('s_add'))$('s_add').onclick=()=>{if(!sel)return flash('Chưa chọn vùng trên văn bản',1);cur.expected.push({doc_id:docv.doc_id,char_start:sel.s,char_end:sel.e,quote:docv_text(sel.s,sel.e)});sel=null;refreshSpans()};
 if($('s_rep'))$('s_rep').onclick=()=>{if(!sel||repl<0)return flash('Chọn một span và một vùng',1);cur.expected[repl]={doc_id:docv.doc_id,char_start:sel.s,char_end:sel.e,quote:docv_text(sel.s,sel.e)};sel=null;repl=-1;refreshSpans()}}
function docv_text(s,e){return docv.text.slice(s-docv.offset,e-docv.offset)}
function drawDoc(){if(!docv||!$('doc'))return;$('dtitle').textContent=docv.title.slice(0,100);$('dinfo').textContent=`${docv.doc_type} · ${docv.status} · khóa ${docv.khoa.map(x=>x??'∞').join('–')} · ${docv.total} ký tự`;
 const hl=[];(cur.expected||[]).forEach((e,i)=>{if(e.doc_id===docv.doc_id)hl.push({s:e.char_start,e:e.char_end,c:i===repl?'cur':'sp'})});if(sel)hl.push({s:sel.s,e:sel.e,c:'sel'});renderDoc($('doc'),docv.text,docv.offset,hl);
 const m=$('doc').querySelector('mark.sp,mark.cur');if(m&&!window._scrolled){m.scrollIntoView({block:'center'});window._scrolled=1}}
function renderDoc(el,text,base,hl){const pts=new Set([0,text.length]);for(const h of hl){pts.add(Math.max(0,Math.min(text.length,h.s-base)));pts.add(Math.max(0,Math.min(text.length,h.e-base)))}
 const P=[...pts].sort((a,b)=>a-b);let h='';for(let i=0;i<P.length-1;i++){const a=P[i],b=P[i+1];if(a===b)continue;const g=base+a;const cov=hl.filter(x=>x.s<=g&&x.e>=base+b);const c=cov.find(x=>x.c==='sel')||cov.find(x=>x.c==='cur')||cov[0];
  h+=c?`<mark class="${c.c}" data-o="${g}">${esc(text.slice(a,b))}</mark>`:`<span data-o="${g}">${esc(text.slice(a,b))}</span>`}el.innerHTML=h}
function go0(n){const o=n.nodeType===3?n.parentElement:n;const p=o.closest('[data-o]');return p}
function selOff(root){const s=getSelection();if(!s.rangeCount||s.isCollapsed)return null;const r=s.getRangeAt(0);if(!root.contains(r.commonAncestorContainer))return null;
 const f=(n,o,end)=>{if(n.nodeType===3){const p=go0(n);return p?+p.dataset.o+o:null}const ch=n.childNodes[o];if(ch){const p=ch.nodeType===1&&ch.dataset&&ch.dataset.o!=null?ch:go0(ch);return p?+p.dataset.o:null}const l=n.lastChild;return l&&l.dataset?+l.dataset.o+l.textContent.length:null};
 const a=f(r.startContainer,r.startOffset),b=f(r.endContainer,r.endOffset);if(a==null||b==null||b<=a)return null;return{s:a,e:b}}
function bindSel(){bindSpanBtns();const d=$('doc');if(!d)return;d.onmouseup=()=>{const o=selOff(d);if(!o)return;sel=o;getSelection().removeAllRanges();$('selinfo').textContent=`vùng chọn [${o.s}-${o.e}] (${o.e-o.s} ký tự)`+(repl>=0?`; thay span #${repl+1}`:'');if($('s_rep'))$('s_rep').disabled=repl<0;drawDoc()};
 $('d_more').onclick=async()=>{const e=cur.expected[0]||{char_start:0,char_end:0};docv=await api(`/api/doc?doc_id=${docv.doc_id}&start=${docv.offset}&end=${docv.offset+docv.text.length}&pad=3000`);drawDoc()};
 $('d_full').onclick=async()=>{docv=await api(`/api/doc?doc_id=${docv.doc_id}&full=1`);drawDoc()}}
function collect(){const q={id:cur.id,question:$('q_q').value,type:$('q_t').value,khoa:$('q_k').value.trim()===''?null:$('q_k').value.trim(),expected_behavior:$('q_b').value,note:$('note').value,reason:$('rs').value,reviewer:$('who').value};
 if($('q_a'))q.answer_ref=$('q_a').value;if(cur.expected_behavior!=='refuse'&&$('q_b').value==='refuse')q.expected=[];else if($('spans'))q.expected=cur.expected.map(e=>({doc_id:e.doc_id,char_start:e.char_start,char_end:e.char_end}));
 if($('x_kt'))q.xac_nhan_kien_thuc_chung=$('x_kt').checked||null;if($('x_ten'))q.xac_nhan_ten=$('x_ten').checked||null;return q}
async function act(a){if(!cur)return;const q=collect();if(!q.reviewer)return flash('Nhập tên người duyệt trước',1);q.action=a;const r=await api('/api/review',q);if(!r.ok)return flash(r.loi,1);flash(`${a}: ${r.status}`+(r.changed&&r.changed.length?` (đã sửa: ${r.changed.join(', ')})`:''));window._scrolled=0;await loadQueue(idx)}
function go(d){if(!items.length)return;const i=Math.max(0,Math.min(items.length-1,idx+d));window._scrolled=0;openIdx(i)}
function probeUI(){return `<div class="row"><button class="b pri" id="pr">Chạy thử retrieval (hybrid, c2)</button><span class="hint">Xem kho có THẬT SỰ không chứa câu trả lời. Nếu có: Loại với lý do "kho có câu trả lời".</span></div><div id="pres"></div>`}
async function probe(){$('pres').innerHTML='<span class="hint">đang chạy...</span>';const r=await api('/api/probe',{question:$('q_q').value,user_ctx:cur.user_ctx});
 if(!r.ok){$('pres').innerHTML=`<span class="err">${esc(r.loi)}</span>`;return}$('pres').innerHTML=r.top.map(t=>`<div class="probe"><b>#${t.rank}</b> điểm ${t.score} · ${esc(t.doc_id.slice(0,16))}<br>${esc(t.breadcrumb)}<br><span class="hint">${esc(t.snippet)}</span></div>`).join('')}
document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea,select')||e.ctrlKey||e.metaKey||e.altKey||(mode!=='llm'&&mode!=='oos'))return;const k=e.key.toLowerCase();
 if(k==='a')act('accept');else if(k==='e')act('edit');else if(k==='r')act('reject');else if(k==='u')act('unsure');else if(k==='j'||k==='arrowright')go(1);else if(k==='k'||k==='arrowleft')go(-1)});
// ---- thêm câu người viết
let addSpans=[],addDoc=null;
function viewAdd(){addSpans=[];addDoc=null;sel=null;$('main').innerHTML=`<div class="card"><b>Thêm câu do người viết</b> <span class="hint">viết như sinh viên thật hỏi, rồi chọn span đáp án trên văn bản</span>
 <div class="hint">Câu hỏi</div><textarea id="h_q" rows="2"></textarea><div class="hint">Câu trả lời (ngắn)</div><textarea id="h_a" rows="2"></textarea>
 <div class="row">Loại <select id="h_t">${state.types.map(t=>`<option>${t}</option>`).join('')}</select> Khóa <input id="h_k" size="3"> Hành vi <select id="h_b"><option>answer</option><option>ask_clarify_or_multi_version</option><option>refuse</option></select></div></div>
 <div class="card"><div class="row">Tài liệu: <select id="h_dt"><option value="">mọi loại</option>${state.doc_types.map(d=>`<option>${d}</option>`).join('')}</select><input id="h_s" size="30" placeholder="tìm theo tiêu đề / mã"><button class="b" id="h_go">Tìm</button></div><div id="h_list" style="max-height:140px;overflow:auto"></div></div>
 <div class="card"><div class="row"><b id="dtitle"></b><span class="hint" id="dinfo"></span><button class="b" id="h_full">Toàn văn</button><span id="selinfo" class="hint">chưa chọn vùng</span><button class="b" id="s_add">+ Thêm vùng chọn làm span</button></div><div id="spans"></div><div id="doc"></div></div>
 <div class="row"><button class="b ok" id="h_save">Lưu câu hỏi</button></div>`;
 $('h_go').onclick=findDocs;findDocs();$('h_save').onclick=saveHuman}
async function findDocs(){const l=await api(`/api/docs?doc_type=${encodeURIComponent($('h_dt').value)}&q=${encodeURIComponent($('h_s').value)}`);$('h_list').innerHTML=l.map(d=>`<div class="it" style="cursor:pointer;padding:3px" data-d="${esc(d.doc_id)}"><span class="chip">${esc(d.doc_type)}</span> ${esc(d.title)}</div>`).join('');
 for(const e of $('h_list').querySelectorAll('.it'))e.onclick=async()=>{docv=await api(`/api/doc?doc_id=${e.dataset.d}&full=1`);cur={expected:addSpans};sel=null;repl=-1;window._scrolled=1;drawAdd()}}
function drawAdd(){cur.expected=addSpans;drawDoc();$('spans').innerHTML=addSpans.map((e,i)=>spanRow(e,i)).join('');bindAdd()}
function bindAdd(){const d=$('doc');d.onmouseup=()=>{const o=selOff(d);if(!o)return;sel=o;getSelection().removeAllRanges();$('selinfo').textContent=`vùng chọn [${o.s}-${o.e}]`;drawDoc()};
 $('s_add').onclick=()=>{if(!sel)return flash('Chưa chọn vùng',1);addSpans.push({doc_id:docv.doc_id,char_start:sel.s,char_end:sel.e,quote:docv_text(sel.s,sel.e)});sel=null;drawAdd()};$('h_full').onclick=()=>{}}
window.pickSpan=window.pickSpan;window.delSpan=i=>{if(mode==='add'){addSpans.splice(i,1);drawAdd()}else{cur.expected.splice(i,1);repl=-1;refreshSpans()}};
async function saveHuman(){const b=$('h_b').value;const r=await api('/api/add',{question:$('h_q').value,answer_ref:$('h_a').value,type:$('h_t').value,khoa:$('h_k').value.trim()||null,expected_behavior:b,reviewer:$('who').value,expected:b==='refuse'?[]:addSpans.map(e=>({doc_id:e.doc_id,char_start:e.char_start,char_end:e.char_end}))});
 if(!r.ok)return flash(r.loi,1);flash(`Đã lưu ${r.id} (trùng từ ${r.lexical_overlap})`);viewAdd()}
// ---- tổng kết
async function viewSum(){const s=await api('/api/summary');const T=['pending','accepted','edited','rejected','unsure'];
 $('main').innerHTML=`<div class="card"><b>Tổng ${s.total} câu</b> · ${esc(JSON.stringify(s.by_status))}<br><span class="hint">Đã chấp nhận: dev/test ${esc(JSON.stringify(s.split))} · hành vi ${esc(JSON.stringify(s.behavior))} · người viết ${s.human} · phụ thuộc khóa ${s.khoa_phu_thuoc}</span></div>
 <div class="card"><b>Trạng thái × doc_type</b><table><tr><th></th>${T.map(x=>`<th>${x}</th>`).join('')}</tr>${Object.entries(s.status_x_doctype).map(([d,c])=>`<tr><td>${esc(d)}</td>${T.map(x=>`<td>${c[x]||0}</td>`).join('')}</tr>`).join('')}</table></div>
 <div class="card"><b>Đã chấp nhận: type × doc_type</b><table><tr><th></th>${state.types.map(x=>`<th>${x}</th>`).join('')}</tr>${Object.entries(s.type_x_doctype_accepted).map(([d,c])=>`<tr><td>${esc(d)}</td>${state.types.map(x=>`<td>${c[x]||0}</td>`).join('')}</tr>`).join('')}</table></div>
 <div class="card"><b>Độ trùng từ</b> (trung bình ${s.overlap_mean}, trung vị ${s.overlap_median}; cao quá thì kết quả thiên về BM25)<table><tr><th>khoảng</th><th>số câu</th></tr>${s.overlap_hist.map((n,i)=>`<tr><td>${(i/10).toFixed(1)}–${((i+1)/10).toFixed(1)}</td><td>${n}</td></tr>`).join('')}</table></div>
 <div class="card"><b>Người duyệt</b> ${esc(JSON.stringify(s.reviewers))} <button class="b" id="exp">Xuất questions_summary.md</button> <span id="expm"></span></div>`;
 $('exp').onclick=async()=>{const r=await api('/api/summary/export',{});$('expm').textContent=r.ok?'Đã ghi '+r.file:r.loi}}
init();
</script></body></html>"""

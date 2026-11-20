"""Crawler thanglong.edu.vn/vi bằng trình duyệt headless (Playwright).

Chỉ mở các trang công khai như người dùng thường; KHÔNG gọi API nội bộ của CMS.
Đầu ra (chỉ ghi vào data/raw/, giữ nguyên dữ liệu gốc):
    data/raw/pages/<topic>/<slug>.json   nội dung + metadata từng trang
    data/raw/files/<tên file>            PDF/DOCX/XLSX đính kèm
    data/raw/manifest.jsonl              mỗi dòng một trang: url, chủ đề, ngày crawl, file, hash
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

from playwright.sync_api import Page, sync_playwright

from rag.config import RAW_DIR, load_config

FILE_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar")
DRIVE_RE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
# Bỏ phần khung trang (đầu/cuối) khi lấy text nội dung.
STRIP_JS = """() => {
  document.querySelectorAll('header, footer, nav, script, style, noscript').forEach(e => e.remove());
  return document.body.innerText;
}"""
# Mở các accordion/tab đang đóng để lấy hết nội dung.
EXPAND_JS = """() => {
  document.querySelectorAll('[data-state="closed"][aria-expanded], button[aria-expanded="false"]')
    .forEach(b => { try { b.click(); } catch (e) {} });
}"""


def norm(text: str) -> str:
    """Hạ chữ thường + bỏ dấu để so khớp từ khóa."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def sniff_ext(body: bytes, ctype: str = "") -> str:
    if body.startswith(b"%PDF"):
        return ".pdf"
    if body.startswith(b"PK"):
        head = body[:4000]
        if b"word/" in head:
            return ".docx"
        if b"xl/" in head:
            return ".xlsx"
        if b"ppt/" in head:
            return ".pptx"
        return ".zip"
    if body[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return ".jpg"
    if body[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
        return ".png"
    if body[:4] == bytes([0xD0, 0xCF, 0x11, 0xE0]):
        return ".doc"
    return ".pdf" if "pdf" in ctype else ".bin"


def slugify(text: str, limit: int = 120) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")
    return s[:limit] or "page"


def trim_text(text: str) -> str:
    """Bỏ khung trang (menu đầu, chân trang) khỏi text lấy từ body."""
    nl = chr(10)
    for marker in ("GIẤY TỜ LIÊN QUAN", "VỀ CHÚNG TÔI", "Copyright ©"):
        i = text.find(marker)
        if i > 0:
            tail = (nl * 2 + marker) if marker == "GIẤY TỜ LIÊN QUAN" else ""
            text = text[:i].rstrip() + tail
    # Menu đầu trang kết thúc ở breadcrumb "Trang chủ".
    crumb = nl + "Trang chủ" + nl
    i = text[:3000].find(crumb)
    if i >= 0:
        text = text[i + len(crumb):]
    while nl * 3 in text:
        text = text.replace(nl * 3, nl * 2)
    return text.strip()


def parse_date(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


class Crawler:
    def __init__(self, cfg: dict | None = None, force: bool = False):
        self.cfg = cfg or load_config("sources")
        self.opt = self.cfg["crawl"]
        self.base = self.cfg["base_url"].rstrip("/")
        self.force = force
        self.pages_dir = RAW_DIR / "pages"
        self.files_dir = RAW_DIR / "files"
        self.manifest_path = RAW_DIR / "manifest.jsonl"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_manifest()
        self.topic_kw = {
            t: [norm(k) for k in kws] for t, kws in self.cfg["announcement_topics"].items()
        }
        self._last = 0.0

    # ---------- manifest ----------
    def _load_manifest(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    out[rec["url"]] = rec
        return out

    def _save_manifest(self) -> None:
        with self.manifest_path.open("w", encoding="utf-8") as f:
            for rec in self.manifest.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- tiện ích ----------
    def _wait(self) -> None:
        gap = self.opt["delay_seconds"] - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.time()

    def _goto(self, page: Page, url: str) -> None:
        self._wait()
        page.goto(url, wait_until="networkidle", timeout=self.opt["page_timeout_ms"])
        page.wait_for_timeout(1000)

    def classify(self, title: str) -> str | None:
        t = norm(title)
        for topic, kws in self.topic_kw.items():
            if any(re.search("(?<![a-z0-9])" + re.escape(k) + "(?![a-z0-9])", t) for k in kws):
                return topic
        return None

    def _collect_files(self, page: Page) -> list[dict]:
        """Link tài liệu trong nội dung: file trực tiếp + Google Drive (iframe/link)."""
        found: dict[str, dict] = {}
        srcs = page.eval_on_selector_all(
            "a[href], iframe[src]",
            "els => els.map(e => [e.getAttribute('href') || e.getAttribute('src'),"
            " (e.innerText || '').trim()])",
        )
        for href, label in srcs:
            if not href or href.startswith(("mailto:", "tel:", "#")):
                continue
            url = urljoin(page.url, href)
            for local in ("http://localhost:18000", "http://localhost:8000", "http://supabase-kong:8000"):
                url = url.replace(local, self.cfg["crawl"].get("media_base", "https://media-cms.thanglong.edu.vn"))
            m = DRIVE_RE.search(url)
            if m:
                fid = m.group(1)
                found[url] = {"kind": "drive", "id": fid, "url": f"https://drive.google.com/file/d/{fid}/view",
                              "label": label}
            elif urlparse(url).path.lower().endswith(FILE_EXT):
                found[url] = {"kind": "direct", "url": url, "label": label}
        return list(found.values())

    def _download(self, page: Page, f: dict) -> None:
        """Tải file về data/raw/files. Lỗi thì ghi 'error', không dừng crawl."""
        if not self.opt["download_files"]:
            return
        if f["kind"] == "drive":
            url = f"https://drive.google.com/uc?export=download&id={f['id']}"
            base = f"drive-{f['id']}"
        else:
            url = f["url"]
            base = Path(unquote(urlparse(url).path)).name
        try:
            self._wait()
            resp = None
            candidates = [url]
            if f["kind"] == "direct":  # tên file tiếng Việt: thử NFC/NFD và percent-encode
                pr = urlparse(url)
                for form in ("NFC", "NFD"):
                    path = quote(unicodedata.normalize(form, unquote(pr.path)), safe="/")
                    candidates.append(pr._replace(path=path).geturl())
            for cand in candidates:
                resp = page.context.request.get(cand, timeout=self.opt["page_timeout_ms"])
                if resp.ok and "text/html" not in resp.headers.get("content-type", ""):
                    break
            ctype = resp.headers.get("content-type", "")
            body = resp.body()
            if not resp.ok or "text/html" in ctype:
                f["error"] = f"không tải được (HTTP {resp.status}, {ctype or 'n/a'})"
                return
            if len(body) > self.opt["max_file_mb"] * 1024 * 1024:
                f["error"] = "vượt quá max_file_mb"
                return
            ext = Path(base).suffix.lower() or sniff_ext(body, ctype)
            stem = Path(base).stem if f["kind"] == "direct" else base
            dest = self.files_dir / (re.sub(r"[^\w.\-]+", "-", stem)[:100] + ext)
            dest.write_bytes(body)
            f["local_path"] = str(dest.relative_to(RAW_DIR.parent.parent)).replace("\\", "/")
            f["sha256"] = hashlib.sha256(body).hexdigest()
            f["bytes"] = len(body)
        except Exception as e:  # noqa: BLE001
            f["error"] = f"{type(e).__name__}: {e}"

    def _save_page(self, rec: dict) -> None:
        d = self.pages_dir / rec["topic"]
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{slugify(urlparse(rec['url']).path.rsplit('/', 1)[-1] or rec['title'])}.json"
        text_hash = hashlib.sha256(rec["text"].encode("utf-8")).hexdigest()
        rec["content_hash"] = text_hash
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self.manifest[rec["url"]] = {
            "url": rec["url"], "topic": rec["topic"], "title": rec["title"], "date": rec.get("date"),
            "crawled_at": rec["crawled_at"], "page_file": str(path.relative_to(RAW_DIR.parent.parent)).replace("\\", "/"),
            "files": [f.get("local_path") or f["url"] for f in rec["files"]],
            "content_hash": text_hash,
        }

    def _page_record(self, page: Page, url: str, topic: str, extra: dict | None = None) -> dict:
        self._goto(page, url)
        page.evaluate(EXPAND_JS)
        page.wait_for_timeout(500)
        files = self._collect_files(page)  # lấy link trước khi STRIP_JS xóa phần tử
        title = (page.title() or "").replace(" - Thang Long University", "").strip()
        text = page.evaluate(STRIP_JS)
        text = trim_text(text)
        for f in files:
            self._download(page, f)
        rec = {
            "url": url, "topic": topic, "title": title, "text": text, "files": files,
            "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "thanglong.edu.vn",
        }
        rec.update(extra or {})
        return rec

    # ---------- trang tĩnh ----------
    def crawl_static(self, page: Page) -> int:
        n, seen = 0, set()
        patterns = self.cfg.get("follow_patterns", [])
        for item in self.cfg["static_pages"]:
            url = self.base + item["path"]
            if url in seen or (url in self.manifest and not self.force):
                continue
            seen.add(url)
            try:
                rec = self._page_record(page, url, item["topic"])
            except Exception as e:  # noqa: BLE001
                print(f"  ! lỗi {url}: {e}")
                continue
            self._save_page(rec)
            n += 1
            print(f"  [static] {item['topic']}: {url}")
            if patterns:  # đi theo link con (1 bước)
                links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                for link in sorted({l.split('#')[0] for l in links}):
                    if any(p in link for p in patterns) and link not in seen \
                            and (link not in self.manifest or self.force):
                        seen.add(link)
                        try:
                            self._save_page(self._page_record(page, link, item["topic"], {"parent": url}))
                            n += 1
                            print(f"    [follow] {link}")
                        except Exception as e:  # noqa: BLE001
                            print(f"    ! lỗi {link}: {e}")
        return n

    # ---------- thông báo ----------
    def _list_items(self, page: Page) -> list[dict]:
        rows = page.eval_on_selector_all(
            "a[href*='/thong-bao/']",
            "els => els.map(e => [e.getAttribute('href'), (e.innerText||'').trim(),"
            " (e.closest('div')||e).parentElement ? e.parentElement.innerText : ''])",
        )
        items: dict[str, dict] = {}
        for href, label, ctx in rows:
            if not label or href.rstrip("/").endswith("/thong-bao"):
                continue
            url = urljoin(self.base, href)
            items.setdefault(url, {"url": url, "title": label.split("\n")[0], "date": parse_date(ctx)})
        return list(items.values())

    def crawl_announcements(self, page: Page) -> int:
        self._goto(page, f"{self.base}{self.cfg['lang_prefix']}/thong-bao")
        since = self.opt.get("announcements_since_year")
        matched: list[dict] = []
        seen_urls: set[str] = set()
        for i in range(1, self.opt["announcements_max_pages"] + 1):
            items = self._list_items(page)
            new = [it for it in items if it["url"] not in seen_urls]
            if not new:
                break
            for it in new:
                seen_urls.add(it["url"])
                topic = self.classify(it["title"])
                if topic:
                    it["topic"] = topic
                    matched.append(it)
            dates = [it["date"] for it in new if it["date"]]
            print(f"  [list] trang {i}: {len(new)} thông báo, khớp chủ đề tới nay: {len(matched)}")
            if since and dates and max(dates) < f"{since}-01-01":
                break  # danh sách sắp theo mới nhất → các trang sau cũ hơn mốc
            nxt = page.query_selector("a[aria-label='Go to next page']")
            if not nxt or nxt.get_attribute("aria-disabled") == "true":
                break
            first = new[0]["url"]
            self._wait()
            nxt.click()
            try:
                page.wait_for_function(
                    "u => !document.querySelector(`a[href*=\"${u}\"]`)",
                    arg=urlparse(first).path, timeout=15000)
            except Exception:  # noqa: BLE001
                page.wait_for_timeout(2500)
        n = 0
        for it in matched:
            if since and it["date"] and it["date"] < f"{since}-01-01":
                continue
            if it["url"] in self.manifest and not self.force:
                continue
            try:
                rec = self._page_record(page, it["url"], it["topic"], {"list_date": it["date"]})
            except Exception as e:  # noqa: BLE001
                print(f"  ! lỗi {it['url']}: {e}")
                continue
            m = DATE_RE.search(rec["text"].split("Chi tiết", 1)[-1])
            rec["date"] = parse_date(m.group(0)) if m else it["date"]
            rec["title"] = it["title"] or rec["title"]
            self._save_page(rec)
            n += 1
            print(f"  [tb] {it['topic']}: {rec['title'][:80]}")
            if n % 20 == 0:
                self._save_manifest()
        return n

    # ---------- chạy ----------
    def run(self, headless: bool = True) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(user_agent=self.opt["user_agent"], locale="vi-VN")
            page = ctx.new_page()
            try:
                print("== Trang tĩnh ==")
                a = self.crawl_static(page)
                self._save_manifest()
                print("== Thông báo ==")
                b = self.crawl_announcements(page)
            finally:
                self._save_manifest()
                browser.close()
        print(f"Xong: {a} trang tĩnh, {b} thông báo mới. Manifest: {self.manifest_path}")

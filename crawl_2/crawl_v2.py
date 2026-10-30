"""Crawl du lieu hoc vu / dao tao cua Truong DH Thang Long -> crawl_v2.csv, crawl_v2.json.

Nguon: API doc cong khai ma chinh website dung (api-cms.thanglong.edu.vn/api/v1):
    /announcements/{id}   thong bao, quyet dinh (id lay tu sitemap.xml)
    /pages/code/{code}    trang CMS (nganh hoc, co cau to chuc, lien he, ...)
Chi doc (GET), nghi giua cac request, cache ket qua vao data/raw_api/.

Chay:  python crawl_v2.py
"""
import csv
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SITE = "https://thanglong.edu.vn"
API = "https://api-cms.thanglong.edu.vn/api/v1"
MEDIA = "https://media-cms.thanglong.edu.vn"
DELAY = 1.0  # giay giua cac request that
UA = "Mozilla/5.0 (research crawler; contact: nguyenvanphuc10124@gmail.com)"

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "raw_api"
OUT_CSV = ROOT / "crawl_v2.csv"
OUT_JSON = ROOT / "crawl_v2.json"

# Trang CMS can lay: (code, category, source path tren website)
PAGES = [
    ("dao-tao", "chuong_trinh_dao_tao", "/vi/dao-tao"),
    ("dai-hoc-chinh-quy", "chuong_trinh_dao_tao", "/vi/dao-tao/dai-hoc-chinh-quy"),
    ("sau-dai-hoc", "chuong_trinh_dao_tao", "/vi/dao-tao/sau-dai-hoc"),
    ("lien-ket-quoc-te", "chuong_trinh_dao_tao", "/vi/dao-tao/lien-ket-quoc-te"),
    ("lien-thong", "chuong_trinh_dao_tao", "/vi/dao-tao/lien-thong"),
    ("sinh-vien-hien-tai", "thong_tin_sinh_vien", "/vi/sinh-vien-hien-tai"),
    ("tai-lieu-hoc-tap", "thong_tin_sinh_vien", "/vi/sinh-vien-hien-tai/tai-lieu-hoc-tap"),
    ("co-cau-to-chuc", "chuc_nang_don_vi", "/vi/co-cau-to-chuc"),
    ("lien-he", "thong_tin_lien_lac", "/vi/lien-he"),
]

# Thong bao tuyen sinh / nhap hoc / ket qua trung tuyen khong thuoc 6 nhom yeu cau -> bo qua.
ANN_EXCLUDE = re.compile(r"trúng tuyển|tuyển sinh|xét tuyển|thủ tục nhập học|lệ phí nhập học|ngưỡng đảm bảo|công nhận (học viên|nghiên cứu sinh)", re.I)

# Phan loai thong bao theo tieu de, khop tu tren xuong, khop dau tien thang.
# (category, regex). Cac category khac cung khop duoc ghi vao "tags".
ANN_RULES = [
    ("hoc_phi", r"học phí|lệ phí|định mức thu|mức thu|thu phí"),
    ("mon_thay_the", r"thay thế|môn tương đương|học phần tương đương"),
    ("tkb", r"thời khóa biểu|thời khoá biểu|\btkb\b|lịch học|phòng học|dạy bù|nghỉ học"),
    ("lich_thi", r"lịch thi|lịch kiểm tra|kỳ thi|kì thi|\bthi\b|phúc khảo|phúc tra|điểm (tổng kết|thi)|kiểm tra giữa"),
    ("chuong_trinh_dao_tao", r"chương trình đào tạo|chuẩn chương trình|đề cương chi tiết|bản mô tả"),
    ("quy_che", r"quy chế|quy định|quy trình|hướng dẫn|chuyển (chương trình|ngành)|đăng ký học|bảo vệ|"
                r"khóa luận|khoá luận|luận (văn|án)|tốt nghiệp|xét (tốt nghiệp|học bổng)|thực tập|chuẩn đầu ra"),
    ("ke_hoach_dao_tao", r"kế hoạch|lịch (đào tạo|học kỳ)|tiến độ|biểu đồ|tập trung sinh viên|giáo dục quốc phòng|"
                         r"hủy lớp|cố vấn học tập|sinh hoạt công dân|học kỳ (phụ|hè)"),
]
ANN_RULES = [(c, re.compile(p, re.I)) for c, p in ANN_RULES]

SKIP_KEYS = {
    "id", "type", "image", "images", "imageSrc", "src", "icon", "color", "backgroundColor", "className",
    "variant", "alt", "altText", "hidden", "breadcrumbPage", "breadcrumbItems", "video", "banner",
    "banner_mobile", "viewMore", "viewDetails", "explore", "background", "logo", "thumbnail",
}
LINK_KEYS = {"href", "link", "linkHref", "url"}
UNIT_LISTS = {"fields", "sections", "departments", "faculties", "units"}


def fetch(url, cache_name):
    """GET JSON, co cache tren dia. Tra None neu 404/loi."""
    path = CACHE / cache_name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"  ! {e.code} {url}")
        return None
    except urllib.error.URLError as e:
        print(f"  ! {e.reason} {url}")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return json.loads(raw)


def fetch_text(url):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def clean_url(u):
    """Lam sach link: iframe nhung, link localhost cua CMS cu, link tuong doi."""
    if not isinstance(u, str):
        return ""
    u = u.strip()
    m = re.search(r'src="([^"]+)"', u)
    if m:
        u = m.group(1)
    u = u.replace("http://localhost:18000", MEDIA)
    if u.startswith("/") and not u.startswith("//"):
        u = SITE + u
    return u if u.startswith(("http://", "https://", "mailto:", "tel:")) else ""


def doc_text(node):
    """Lay chu tu tai lieu kieu ProseMirror/TipTap."""
    if isinstance(node, dict):
        if node.get("text"):
            return node["text"]
        parts = [doc_text(c) for c in (node.get("content") or [])]
        sep = "\n" if node.get("type") in {"doc", "bulletList", "orderedList"} else ""
        return sep.join(p for p in parts if p)
    if isinstance(node, list):
        return "\n".join(p for p in (doc_text(c) for c in node) if p)
    return ""


def flatten(obj, texts, links):
    """Gom moi chuoi chu va link trong khoi CMS, bo qua anh/mau/id."""
    if isinstance(obj, dict):
        if isinstance(obj.get("label"), str) and isinstance(obj.get("text"), str):
            texts.append(f"{obj['label']}: {obj['text'].strip()}")
            u = clean_url(obj.get("href", ""))
            if not u and re.fullmatch(r"[\d ]{8,}", str(obj.get("href", "")).strip()):
                u = "tel:" + str(obj["href"]).replace(" ", "")
            if u:
                links.append({"name": obj["label"], "url": u})
            return
        for k, v in obj.items():
            if k in SKIP_KEYS:
                continue
            if k in LINK_KEYS and isinstance(v, str):
                u = clean_url(v)
                if u and v != "#":
                    links.append({"name": str(obj.get("name") or obj.get("title") or obj.get("text") or ""), "url": u})
            elif k == "email" and isinstance(v, str) and v.strip():
                texts.append(f"Email: {v.strip()}")
                links.append({"name": "email", "url": "mailto:" + v.strip()})
            elif k == "number" and isinstance(v, str):
                texts.append(f"Điện thoại: {v.strip()}")
            else:
                flatten(v, texts, links)
    elif isinstance(obj, list):
        for v in obj:
            flatten(v, texts, links)
    elif isinstance(obj, str):
        s = re.sub(r"<[^>]+>", " ", obj).strip()
        if s and not s.startswith(("http", "/", "#")):
            texts.append(s)


def slugify(text, limit=60):
    t = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:limit]


def dedupe(seq, key=lambda x: x):
    seen, out = set(), []
    for x in seq:
        k = key(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def make(id_, category, title, content, links, source_url, **extra):
    rec = {
        "id": id_,
        "category": category,
        "title": title,
        "date": extra.pop("date", ""),
        "department": extra.pop("department", ""),
        "content": content.strip(),
        "links": dedupe(links, key=lambda l: l["url"]),
        "source_url": source_url,
        "tags": extra.pop("tags", []),
        "crawled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    rec["content_hash"] = hashlib.sha1(rec["content"].encode("utf-8")).hexdigest()[:12]
    rec.update(extra)
    return rec


def page_records(code, category, path, data):
    """Mot trang CMS -> 1 ban ghi trang, them 1 ban ghi cho moi don vi (phong/khoa) neu co."""
    blocks = data.get("page_data", {}).get("content", [])
    title = data.get("name") or code
    texts, links, units = [], [], []
    for b in blocks:
        props = b.get("props", {})
        if b.get("type") == "FormalBanner" and props.get("title"):
            title = props["title"]
        for key, val in props.items():
            if key in UNIT_LISTS and isinstance(val, list) and val and isinstance(val[0], dict):
                for it in val:
                    units.append((props.get("title", ""), it))
        flatten({k: v for k, v in props.items() if k not in UNIT_LISTS}, texts, links)
    recs = []
    src = SITE + path
    recs.append(make(f"page-{code}", category, title, "\n".join(dedupe(texts)), links, src, content_type="page"))
    for sec_title, it in dedupe(units, key=lambda u: json.dumps(u[1], sort_keys=True)):
        t, l = [], []
        flatten(it, t, l)
        name = it.get("title") or it.get("name") or (t[0] if t else "")
        if not name:
            continue
        slug = slugify(name) or hashlib.sha1(name.encode()).hexdigest()[:8]
        cat = category
        recs.append(make(f"unit-{code}-{slug}", cat, name, "\n".join(dedupe(t)), l, src,
                         content_type="unit", department=name, tags=[sec_title] if sec_title else []))
    return recs


def faculty_names(pages):
    """slug nganh -> ten khoa, lay tu cac the carousel (moi the co 'faculty' la ten khoa)."""
    names = {}
    for data in pages:
        for b in data.get("page_data", {}).get("content", []):
            if b.get("type") == "FeaturedMajorsCarousel":
                for m in b["props"].get("majors", []):
                    if m.get("href") and m.get("faculty"):
                        names[m["href"].rsplit("/", 1)[-1]] = m["faculty"].strip()
    return names


def curriculum_of(program):
    """programs -> [{year, group, subjects[]}]"""
    out = []
    for y in program.get("years", []):
        subs = [s.get("name", "").strip() for s in y.get("subjects", []) if s.get("name")]
        if subs:
            out.append({"year": y.get("trigger", ""), "group": y.get("title", ""), "subjects": subs})
    return out


def major_record(slug, data, faculty_name=""):
    blocks = data.get("page_data", {}).get("content", [])
    title, level, parts, links, curriculum = data.get("name") or slug, "", [], [], []
    for b in blocks:
        p = b.get("props", {})
        if b.get("type") == "FacultyBanner":
            title, level = p.get("title") or title, p.get("level") or ""
        elif b.get("type") == "FacultyInfoTabs":
            for tab in p.get("tabs", []):
                head = (tab.get("trigger") or "").strip()
                lines = []
                for st in tab.get("stats", []):
                    lines.append(f"{st.get('title', '')}: {st.get('value', '')}")
                summ = tab.get("summary") or {}
                for k in ("title", "description", "highlights"):
                    if summ.get(k):
                        lines.append(str(summ[k]).strip())
                if tab.get("content"):
                    lines.append(str(tab["content"]).strip())
                if tab.get("programs"):
                    curriculum = curriculum_of(tab["programs"])
                    for c in curriculum:
                        lines.append(f"{c['year']} - {c['group']}: " + "; ".join(c["subjects"]))
                if lines:
                    parts.append((f"## {head}\n" if head else "") + "\n".join(lines))
    header = [f"Ngành: {title}"]
    if faculty_name:
        header.append(f"Khoa: {faculty_name}")
    if level:
        header.append(level)
    content = "\n".join(header) + "\n\n" + "\n\n".join(parts)
    rec = make(f"nganh-{slug}", "chuong_trinh_dao_tao", title, content, links,
               f"{SITE}/vi/nganh-hoc/{slug}", content_type="major", department=faculty_name)
    rec["curriculum"] = curriculum
    return rec


def classify(title):
    if ANN_EXCLUDE.search(title):
        return None, []
    tags = [c for c, rx in ANN_RULES if rx.search(title)]
    return (tags[0] if tags else None), tags


def announcement_record(d):
    title = (d.get("title") or "").strip()
    cat, tags = classify(title)
    body = doc_text(d.get("content"))
    legacy = re.findall(r"Legacy URL:\s*(\S+)", body)
    body = "\n".join(l for l in body.splitlines() if not l.startswith("Legacy URL:")).strip()
    links = []
    main = clean_url(d.get("main_doc") or "")
    if main:
        links.append({"name": "Văn bản chính", "url": main})
    for r in d.get("related_docs") or []:
        u = clean_url(r.get("href", ""))
        if u:
            links.append({"name": r.get("name") or "Tài liệu đính kèm", "url": u})
    if d.get("thumbnail_image"):
        pass  # anh dai dien, khong phai noi dung
    content = body or title  # nhieu thong bao chi co file dinh kem: giu tieu de lam noi dung chu
    rec = make(f"tb-{d['id']}", cat or "khac", title, content, links,
               f"{SITE}/vi/thong-bao/{d['id']}", content_type="announcement",
               date=(d.get("date") or "")[:10], department=d.get("department") or "",
               tags=tags, announcement_type=(d.get("announcement_type") or {}).get("label", ""))
    if legacy:
        rec["legacy_url"] = legacy[0]
    return rec


def main():
    records = []

    print("== Trang CMS")
    for code, cat, path in PAGES:
        data = fetch(f"{API}/pages/code/{code}", f"pages_{code}.json")
        if data:
            records += page_records(code, cat, path, data)

    print("== Nganh hoc (chuong trinh dao tao)")
    cq = fetch(f"{API}/pages/code/dai-hoc-chinh-quy", "pages_dai-hoc-chinh-quy.json") or {}
    slugs = []
    for b in cq.get("page_data", {}).get("content", []):
        if b.get("type") == "FeaturedMajorsCarousel":
            slugs += [m["href"].rsplit("/", 1)[-1] for m in b["props"].get("majors", []) if m.get("href")]
    # carousel chi liet ke nganh noi bat -> bo sung tu cac link /nganh-hoc/ trong trang goc
    html = fetch_text(f"{SITE}/vi/dao-tao/dai-hoc-chinh-quy")
    slugs += re.findall(r'\\"slug\\":\\"/nganh-hoc/([a-z0-9-]+)\\"', html)
    majors = {}
    for s in dedupe(slugs):
        data = fetch(f"{API}/pages/code/{s}", f"major_{s}.json")
        if data:
            majors[s] = data
    fac = faculty_names([cq, *majors.values()])
    for s, data in majors.items():
        records.append(major_record(s, data, fac.get(s, "")))

    print("== Thong bao")
    sm = fetch_text(f"{SITE}/sitemap.xml")
    ids = sorted({int(i) for i in re.findall(r"/vi/thong-bao/(\d+)", sm)})
    for i in ids:
        d = fetch(f"{API}/announcements/{i}", f"ann_{i}.json")
        if d and d.get("title") and d.get("state", True):
            records.append(announcement_record(d))

    # Giu thong bao thuoc 6 nhom yeu cau; bao cao so bi bo
    kept = [r for r in records if r["content_type"] != "announcement" or r["category"] != "khac"]
    print(f"\nTong {len(records)} ban ghi, bo {len(records) - len(kept)} thong bao khong thuoc nhom yeu cau")
    records = kept
    records.sort(key=lambda r: (r["category"], r["id"]))

    OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    cols = ["id", "category", "content_type", "title", "date", "department", "content", "links",
            "source_url", "tags", "announcement_type", "legacy_url", "curriculum", "crawled_at", "content_hash"]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = dict(r)
            row["links"] = "\n".join(f"{l['name']}: {l['url']}" if l["name"] else l["url"] for l in r["links"])
            row["tags"] = ", ".join(r["tags"])
            row["curriculum"] = json.dumps(r["curriculum"], ensure_ascii=False) if r.get("curriculum") else ""
            w.writerow(row)

    by = {}
    for r in records:
        by[r["category"]] = by.get(r["category"], 0) + 1
    print("Theo nhom:", by)
    print(f"Da ghi {OUT_CSV.name} va {OUT_JSON.name}")


if __name__ == "__main__":
    main()

"""Schema metadata (pydantic) và nạp metadata tài liệu từ configs/doc_meta.yaml + manifest.jsonl.

QUY ƯỚC `null` (quan trọng cho bước retrieval):
    khoa_tu / khoa_den / nganh = None nghĩa là "áp dụng cho TẤT CẢ" (mọi khóa, mọi ngành).
    Khi lọc theo khóa/ngành, chunk có giá trị None PHẢI được coi là KHỚP (ví dụ filter Qdrant:
    `should = [match(khoa_tu <= k <= khoa_den), is_null(khoa_tu)]`). khoa_den = 99 nghĩa là "trở đi".
    Khóa MỘT ĐẦU null: khoa_tu=null, khoa_den=37 nghĩa là "khóa <= 37"; khoa_tu=39, khoa_den=null nghĩa là "khóa >= 39".
    Điều kiện lọc theo khóa K (xem `khoa_matches`):
        (khoa_tu is null OR khoa_tu <= K) AND (khoa_den is null OR khoa_den >= K)
    `bac_dao_tao` (dai_hoc | lien_thong | vua_lam_vua_hoc | sau_dai_hoc | ngan_han) là bắt buộc, dùng làm payload filter.
    GỢI Ý CHO RETRIEVAL: mặc định chỉ lọc `status == "hieu_luc"` VÀ `in_scope == True` (cả hai là payload của mọi chunk);
    chỉ bỏ điều kiện status khi người dùng hỏi rõ về văn bản cũ/đã hết hiệu lực.
    `trung_voi` chỉ có ở DocMeta (tài liệu trùng bị bỏ qua khi chunk), không có trong chunk.
    `in_scope = False` (doc_type "khac") là tài liệu không phải học vụ: lọc bỏ khi truy vấn.
    `ocr_table_suspect = True`: chunk chứa khối >= 4 dòng có ký tự "|" từ trang OCR (bảng chưa dựng lại được).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DocType = Literal["quy_che", "ctdt", "quy_trinh", "ke_hoach", "hoc_phi", "hoc_bong", "mon_thay_the", "lien_he",
                  "lich_thi", "tkb", "thong_bao", "khac"]
Status = Literal["hieu_luc", "het_hieu_luc"]
TableMode = Literal["whole", "rows"]
ConfigName = Literal["c1", "c2", "c3"]
ParserMode = Literal["default", "brochure_by_page"]
BacDaoTao = Literal["dai_hoc", "lien_thong", "vua_lam_vua_hoc", "sau_dai_hoc", "ngan_han"]
DoChac = Literal["chac", "chua_chac", "da_duyet"]


def khoa_matches(khoa_tu: int | None, khoa_den: int | None, k: int) -> bool:
    """Chunk/tài liệu áp dụng cho khóa k? null ở đầu nào thì đầu đó không giới hạn."""
    return (khoa_tu is None or khoa_tu <= k) and (khoa_den is None or khoa_den >= k)


class DocMeta(BaseModel):
    """Metadata cấp tài liệu (xem quy ước null ở đầu module)."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    file: str
    doc_type: DocType
    title: str | None = None
    doc_heading: str | None = None
    source_url: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    posted_date: date | None = None
    issued_date: date | None = None
    status: Status = "hieu_luc"
    khoa_tu: int | None = None
    khoa_den: int | None = None
    nganh: list[str] | None = None
    in_scope: bool = True
    bac_dao_tao: BacDaoTao
    do_chac: DoChac | None = None
    can_kiem_tra: str | None = None  # chỉ để tham khảo, KHÔNG đưa vào chunk
    ghi_chu_duyet: str | None = None  # chỉ để tham khảo, KHÔNG đưa vào chunk
    parser_mode: ParserMode = "default"  # brochure_by_page: tờ rơi, mỗi trang là một mục (không có trong chunk)
    trung_voi: str | None = None  # doc_id của bản được giữ khi tài liệu này là bản trùng -> KHÔNG chunk


class ChunkMeta(BaseModel):
    """Metadata của một chunk: metadata tài liệu + vị trí cấu trúc + vị trí ký tự/trang."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_type: DocType
    title: str | None = None
    source_url: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    posted_date: date | None = None
    issued_date: date | None = None
    status: Status = "hieu_luc"
    khoa_tu: int | None = None
    khoa_den: int | None = None
    nganh: list[str] | None = None
    in_scope: bool = True
    bac_dao_tao: BacDaoTao
    chapter: str | None = None
    article: int | None = None
    clause: int | None = None
    point: str | None = None
    section: str | None = None  # tên heading (tài liệu không có Điều)
    hoc_ky: str | None = None
    ma_hp: str | None = None
    parent_id: str | None = None
    chunk_index: int = 0
    char_start: int
    char_end: int
    page_start: int | None = None
    page_end: int | None = None
    text_routes: list[str] = Field(default_factory=list)
    doc_heading: str | None = None
    is_preamble: bool = False
    fallback: bool = False
    ocr_table_suspect: bool = False
    aliases: list[str] = Field(default_factory=list)
    is_table: bool = False
    table_id: str | None = None
    table_title: str | None = None
    table_mode: TableMode | None = None
    row_start: int | None = None
    row_end: int | None = None
    nganh_ma: str | None = None  # mã ngành của mục ngành chứa chunk (ctdt nhiều ngành, tờ rơi); null nếu chunk không thuộc mục ngành
    nganh_ten: str | None = None  # tên ngành chuẩn (theo configs/nganh.yaml)
    nganh_ma_goc: str | None = None  # mã ngành gốc khi là chương trình riêng của một ngành (7340101A -> 7340101), còn lại null


class Chunk(BaseModel):
    """Một dòng JSONL đầu ra."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    config: ConfigName
    embed_text: str
    content: str
    n_tokens: int
    metadata: ChunkMeta


def _pick_url(urls: list[str]) -> str | None:
    for u in urls:
        if "/thong-bao/" in u:
            return u
    for u in urls:
        if not u.rstrip("/").endswith(("/gioi-thieu", "/cong-khai")):
            return u
    return urls[0] if urls else None


def load_doc_metas(doc_meta_path: Path, manifest_path: Path | None = None) -> dict[str, DocMeta]:
    """Nạp configs/doc_meta.yaml (mục `docs`); trường thiếu được bổ sung từ manifest (source_url, posted_date).

    Chỉ nhận các khóa của DocMeta (bỏ cột phụ của bản nháp: ly_do, tieu_de, goi_y_khoa, do_chac, ...).
    """
    raw = yaml.safe_load(doc_meta_path.read_text(encoding="utf-8")) or {}
    if "docs" not in raw:
        raise ValueError(f"{doc_meta_path}: thiếu khóa `docs`")
    by_file: dict[str, list[dict]] = {}
    if manifest_path and manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            m = json.loads(line)
            for f in m["files"]:
                by_file.setdefault(Path(f).name, []).append(m)
    out: dict[str, DocMeta] = {}
    keys = set(DocMeta.model_fields)
    for doc_id, e in raw.get("docs", {}).items():
        d = {k: v for k, v in e.items() if k in keys}
        d["doc_id"] = doc_id
        ms = by_file.get(e["file"], [])
        urls = d.get("source_urls") or [m["url"] for m in ms]
        d["source_urls"] = urls
        d["source_url"] = d.get("source_url") or _pick_url(urls)
        d["posted_date"] = d.get("posted_date") or next((m["date"] for m in ms if m.get("date")), None)
        d["in_scope"] = e.get("in_scope", d.get("doc_type") != "khac")
        out[doc_id] = DocMeta(**d)
    return out

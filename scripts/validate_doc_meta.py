"""Kiểm tra configs/doc_meta.yaml bằng pydantic (DocMeta) và đối chiếu với data/interim/clean.

Chỉ ĐỌC. Thoát mã 1 nếu có lỗi.
    python scripts/validate_doc_meta.py [đường_dẫn_doc_meta.yaml]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from rag.chunking.metadata import DocMeta, load_doc_metas  # noqa: E402
from rag.config import chunking_config  # noqa: E402

IGNORED_COLUMNS = {"ly_do", "tieu_de", "goi_y_khoa"}  # cột phụ của bản nháp, không nạp vào DocMeta


def main() -> int:
    cfg = chunking_config()
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else cfg["paths"]["doc_meta"]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    if set(raw) != {"docs"}:
        errors.append(f"khóa cấp 1 phải chỉ là `docs`, đang có: {sorted(raw)}")
    docs = raw.get("docs", {})
    fields = set(DocMeta.model_fields)
    unknown = Counter(k for e in docs.values() for k in e if k not in fields and k not in IGNORED_COLUMNS)
    if unknown:
        errors.append(f"khóa lạ (sẽ bị bỏ qua): {dict(unknown)}")
    metas = {}
    for doc_id, e in docs.items():
        try:
            metas[doc_id] = DocMeta(doc_id=doc_id, **{k: v for k, v in e.items() if k in fields and k != "doc_id"})
        except ValidationError as ex:
            errors.append(f"{doc_id}: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in ex.errors()))
    for doc_id, m in metas.items():
        if m.khoa_tu is not None and m.khoa_den is not None and m.khoa_tu > m.khoa_den:
            errors.append(f"{doc_id}: khoa_tu {m.khoa_tu} > khoa_den {m.khoa_den}")
        if m.doc_type == "khac" and m.in_scope:
            errors.append(f"{doc_id}: doc_type=khac nhưng in_scope=true")
        if m.doc_type != "khac" and not m.in_scope:
            print(f"  lưu ý: {doc_id[:40]} doc_type={m.doc_type} nhưng in_scope=false (hợp lệ, tài liệu danh sách cá nhân?)")
        if m.title is None:
            errors.append(f"{doc_id}: thiếu title")
    for doc_id, m in metas.items():
        if m.trung_voi:
            tgt = metas.get(m.trung_voi)
            if tgt is None:
                errors.append(f"{doc_id}: trung_voi={m.trung_voi} không tồn tại trong doc_meta")
            elif tgt.trung_voi:
                errors.append(f"{doc_id}: trung_voi trỏ tới {m.trung_voi} nhưng bản đó cũng có trung_voi")
            elif m.trung_voi == doc_id:
                errors.append(f"{doc_id}: trung_voi trỏ về chính nó")
    print("tài liệu trùng (trung_voi):", [(d[:24], m.trung_voi[:24]) for d, m in metas.items() if m.trung_voi])
    clean = {Path(f).stem: f for f in (json.loads(p.read_text(encoding="utf-8"))["file"] for p in cfg["paths"]["clean_dir"].glob("*.json")
             if p.name != "_manifest.json")}  # doc_id lấy từ trường `file`, không từ tên file trên đĩa (tên đĩa có thể bị đổi dấu)
    missing = sorted(set(clean) - set(metas))
    extra = sorted(set(metas) - set(clean))
    if missing:
        errors.append(f"{len(missing)} tài liệu trong clean/ chưa có trong doc_meta: {missing[:5]}...")
    if extra:
        errors.append(f"{len(extra)} mục doc_meta không có trong clean/: {extra[:5]}...")
    for doc_id, m in metas.items():
        if doc_id in clean and m.file != clean[doc_id]:
            errors.append(f"{doc_id}: file={m.file} khác clean ({clean[doc_id]})")
    try:  # nạp qua đường chính (có nối manifest) để chắc chắn chạy được
        load_doc_metas(path, cfg["paths"]["manifest"])
    except Exception as ex:  # noqa: BLE001
        errors.append(f"load_doc_metas lỗi: {ex}")
    print(f"{path.name}: {len(docs)} mục, {len(metas)} hợp lệ, clean/ có {len(clean)} tài liệu")
    print("doc_type:", dict(Counter(m.doc_type for m in metas.values())))
    print("bac_dao_tao:", dict(Counter(m.bac_dao_tao for m in metas.values())))
    print("in_scope:", dict(Counter(m.in_scope for m in metas.values())), "| do_chac:", dict(Counter(m.do_chac for m in metas.values())))
    kt = sum(1 for m in metas.values() if m.khoa_tu is not None or m.khoa_den is not None)
    one = sum(1 for m in metas.values() if (m.khoa_tu is None) != (m.khoa_den is None))
    print(f"có giới hạn khóa: {kt} (một đầu null: {one})")
    for e in errors:
        print("LỖI:", e)
    print("KẾT QUẢ:", "CÓ LỖI" if errors else "HỢP LỆ")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""Dựng configs/nganh.yaml (danh mục ngành chuẩn) từ dữ liệu: chạy lại được, kết quả cần người duyệt rồi mới dùng.

Nguồn (theo thứ tự ưu tiên tên chuẩn):
  1. "THÔNG-TIN-DANH-MỤC-NGÀNH-ĐÀO-TẠO…": bảng (Tên ngành, Mã ngành) chính thức.
  2. Tờ rơi drive-195f57… (parser brochure_by_page: "<tên> (<mã>)" đầu trang; bảng tổng hợp "Mã xét tuyển | Chương trình đào tạo").
  3. Các QĐ ban hành CTĐT sau đại học: "Tên ngành đào tạo:" + "Mã ngành đào tạo:"; QĐ tiến sĩ: "Ngành X trình độ tiến sĩ, mã số 9 34 01 01".
  4. Mọi bảng khác có ô mã 7 chữ số kèm ô tên: chỉ làm alias (khi tên đủ giống tên chuẩn).
KHÔNG tự thêm alias nào ghép theo tên (không có mã): alias chỉ đến từ bằng chứng có MÃ.

  python scripts/make_nganh_yaml.py            # ghi configs/nganh.yaml
"""
from __future__ import annotations

import re
import sys
from collections import OrderedDict
from difflib import SequenceMatcher
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.chunking.loader import iter_documents  # noqa: E402
from rag.chunking.metadata import load_doc_metas  # noqa: E402
from rag.chunking.parsers.brochure import program_of  # noqa: E402
from rag.chunking.programs import norm_name  # noqa: E402
from rag.chunking.tables.normalize import tables_in  # noqa: E402
from rag.config import ROOT, chunking_config  # noqa: E402

CODE = re.compile(r"^\d{7}[A-Z]?$")
OFFICIAL_DOC = "THÔNG-TIN-DANH-MỤC-NGÀNH-ĐÀO-TẠO_0001"
BROCHURE_DOC = "drive-195f57wSWF1hZEwuF6BXtpVeMrw24OYYf"
MIN_ALIAS_SIM = 0.75


def bac_of(ma: str) -> str:
    return "dai_hoc" if ma.startswith("7") else "sau_dai_hoc"


def main() -> None:
    cfg = chunking_config()
    P = cfg["paths"]
    metas = load_doc_metas(P["doc_meta"], P["manifest"])
    cat: "OrderedDict[str, dict]" = OrderedDict()
    cand: list[tuple[str, str, str]] = []  # (ma, ten gặp, nguồn)

    def add(ma: str, ten: str, nguon: str) -> None:
        ma = re.sub(r"\s+", "", ma)
        ten = re.sub(r"\s+", " ", ten).strip(" .:")
        if ma not in cat:
            cat[ma] = {"ma": ma, "ten": ten, "bac_dao_tao": bac_of(ma), "nguon": nguon, "aliases": []}
        cand.append((ma, ten, nguon))

    docs = {d.doc_id: d for d in iter_documents(P["clean_dir"], None, P["table_vlm_dir"], fixes_path=P["table_vlm_fixes"])
            if metas.get(d.doc_id) and not metas[d.doc_id].trung_voi}
    # 1. danh mục chính thức
    for t in tables_in(docs[OFFICIAL_DOC].text, 0, len(docs[OFFICIAL_DOC].text)):
        for r in t.rows:
            if len(r.cells) > 2 and CODE.match(r.cells[2]):
                add(r.cells[2], r.cells[1], "THÔNG-TIN-DANH-MỤC-NGÀNH-ĐÀO-TẠO (danh mục chính thức)")
    # 2. tờ rơi: trang ngành
    b = docs[BROCHURE_DOC]
    for sp in b.spans:
        prog = program_of(b.text[sp.start:sp.end])
        if prog:
            m = re.match(r"(.+) \((\d{7}[A-Z]?)\)$", prog)
            add(m.group(2), m.group(1), f"tờ rơi {BROCHURE_DOC[:14]}… trang {sp.page}")
    # 3. QĐ sau đại học / tiến sĩ
    rx_ten = re.compile(r"Tên\s+ngành(?:\s+đào\s+tạo)?\s*:\s*(.+)")
    rx_ma = re.compile(r"Mã\s+ngành(?:\s+đào\s+tạo)?\s*:\s*(\d[\d ]{5,9}[A-Z]?)")
    rx_ts = re.compile(r"[Nn]gành\s+(.+?)\s+trình độ\s+tiến sĩ,\s*mã số\s+([\d ]{7,12})")
    for d in docs.values():
        m_ = metas[d.doc_id]
        if m_.doc_type != "ctdt":
            continue
        ten, ma = rx_ten.search(d.text), rx_ma.search(d.text)
        if ten and ma:
            add(ma.group(1), ten.group(1).replace("?", "–"), f"QĐ {d.doc_id[:14]}… (Tên/Mã ngành đào tạo)")
        ts = rx_ts.search(d.text)
        if ts:
            add(ts.group(2), ts.group(1), f"QĐ {d.doc_id[:14]}… (tiến sĩ)")
    # 4. mọi bảng có ô mã + ô tên: chỉ làm alias
    for d in docs.values():
        for t in tables_in(d.text, 0, len(d.text)):
            for r in t.rows:
                codes = [c for c in r.cells if CODE.match(c.replace(" ", ""))]
                names = [c for c in r.cells if re.search(r"[^\W\d_]{3}", c) and not CODE.match(c) and 3 <= len(c) <= 60 and not re.search(r"\d", c)]
                if codes and names and codes[0] in cat:
                    cand.append((codes[0], names[0], f"bảng {d.doc_id[:14]}…"))
    # aliases từ bằng chứng có MÃ, đủ giống tên chuẩn
    skipped = []
    for ma, ten, nguon in cand:
        e = cat[ma]
        if ten.lower() == e["ten"].lower() or ten in e["aliases"]:  # biến thể chỉ khác dấu/lỗi OCR vẫn ghi làm alias (để người duyệt thấy)
            continue
        sim = SequenceMatcher(None, norm_name(ten), norm_name(e["ten"])).ratio()
        (e["aliases"].append(ten) if sim >= MIN_ALIAS_SIM else skipped.append((ma, ten, round(sim, 2), nguon)))
    # quyết định của người duyệt: tên chuẩn 7810103 dùng "và"; biến thể "&" thành alias
    ov = cat.get("7810103")
    if ov and ov["ten"] != "Quản trị dịch vụ du lịch và lữ hành":
        ov["aliases"].append(ov["ten"])
        ov["ten"] = "Quản trị dịch vụ du lịch và lữ hành"
        ov["aliases"] = [a for a in ov["aliases"] if a != ov["ten"]]
    for ma, e in cat.items():  # chương trình riêng của một ngành (mã có chữ cái ở cuối) -> mã ngành gốc; còn lại null
        e["ma_nganh_goc"] = ma[:-1] if ma[-1].isalpha() and ma[:-1] in cat else None
    out = ROOT / "configs" / "nganh.yaml"
    head = ("# Danh mục ngành chuẩn (do scripts/make_nganh_yaml.py dựng từ dữ liệu; NGƯỜI DUYỆT rồi mới dùng, sửa tay được).\n"
            "# ma: mã ngành (7 chữ số + chữ cái tùy chọn = chương trình riêng của cùng mã); ten: tên chuẩn; bac_dao_tao: dai_hoc | sau_dai_hoc;\n"
            "# ma_nganh_goc: mã ngành gốc của chương trình riêng (7340101A -> 7340101); các mục khác null.\n"
            "# aliases: biến thể gặp trong dữ liệu KÈM MÃ (kể cả lỗi OCR). Tên không có mã được ghép bằng so khớp tên chuẩn hóa/difflib >= 0.85\n"
            "# lúc chunking; những tên dưới ngưỡng KHÔNG tự thành alias (xem nganh_unmatched.md).\n")
    items = [{"ma": e["ma"], "ten": e["ten"], "bac_dao_tao": e["bac_dao_tao"], "ma_nganh_goc": e["ma_nganh_goc"], "aliases": sorted(set(e["aliases"])),
              "nguon": e["nguon"]} for e in cat.values()]
    out.write_text(head + yaml.safe_dump({"nganh": items}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    print(f"{len(items)} ngành ghi vào {out}; {sum(len(i['aliases']) for i in items)} alias; bỏ qua {len(skipped)} cặp (mã, tên) quá khác tên chuẩn:")
    for s in skipped[:20]:
        print("  ", s)


if __name__ == "__main__":
    main()

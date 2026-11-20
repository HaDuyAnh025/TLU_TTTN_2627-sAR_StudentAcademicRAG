"""chunk_id cố định giữa các lần chạy, và chunk_corpus không ghi ra ngoài thư mục đầu ra."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from rag.chunking.splitter import chunk_corpus
from rag.config import ROOT

from conftest import PAGE0, PAGE1, make_clean


def snapshot(*dirs: Path) -> dict:
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for d in dirs if d.exists() for p in d.rglob("*") if p.is_file()}


def test_chunk_corpus_deterministic_and_readonly(tmp_path: Path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "qc-mau.json").write_text(json.dumps(make_clean([(PAGE0, "text_layer"), (PAGE1, "text_layer")])), encoding="utf-8")
    meta = tmp_path / "doc_meta.yaml"
    meta.write_text(yaml.safe_dump({"docs": {"qc-mau": {"file": "qc-mau.pdf", "doc_type": "quy_che", "bac_dao_tao": "dai_hoc", "title": "QĐ mẫu"}}}, allow_unicode=True),
                    encoding="utf-8")
    before = snapshot(clean, ROOT / "data" / "interim" / "clean", ROOT / "data" / "raw" / "files")
    ids = []
    for run in ("a", "b"):
        out = tmp_path / f"out_{run}"
        chunk_corpus("all", out_dir=out, clean_dir=clean, doc_meta_path=meta)
        ids.append({cfg: [json.loads(l)["chunk_id"] for l in (out / "chunks" / f"{cfg}_chunks.jsonl").read_text(encoding="utf-8").splitlines()]
                    for cfg in ("c1", "c2")})
        assert (out / "docs" / "qc-mau.txt").exists() and (out / "docs" / "qc-mau.pages.json").exists()
    assert ids[0] == ids[1]
    assert all(len(v) == len(set(v)) for v in ids[0].values())
    assert snapshot(clean, ROOT / "data" / "interim" / "clean", ROOT / "data" / "raw" / "files") == before

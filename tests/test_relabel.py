"""relabel: không xóa thư mục tạm khi còn quyết định chưa merge; merge dry-run không ghi lớp thật."""
from __future__ import annotations

import hashlib
import json

import pytest

from rag.ingestion import relabel
from rag.ingestion.corrections import _write


def rec(pid, items):
    return {"id": pid, "file": f"{pid}.pdf", "page": 0, "items": items, "corrected_text": "", "skipped_items": []}


def item(i, checked, sua="x"):
    return {"item_id": i, "ocr": "a", "anh_llm": "b", "status": "human_applied" if checked else "pending_human", "human_checked": checked, "sua_thanh": sua}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    stage, layer = tmp_path / "stage", tmp_path / "corrected"
    monkeypatch.setattr(relabel, "STAGE_DIR", stage)
    monkeypatch.setattr(relabel.cleaner, "LAYERS", {"corrected": layer})
    return stage, layer


def test_staged_unmerged_counts_pending_and_unmerged_decisions(dirs):
    stage, layer = dirs
    done, todo = item("p0#r0", True), item("p0#r1", False)
    _write(layer, rec("p0", [done, todo]))
    _write(stage, rec("p0", [done, todo]))
    assert relabel.staged_unmerged() == ["p0#r1"]                         # đã merge + chưa duyệt
    _write(stage, rec("p0", [item("p0#r0", True, sua="khác"), item("p0#r1", True)]))  # người duyệt xong nhưng chưa merge về lớp
    assert sorted(relabel.staged_unmerged()) == ["p0#r0", "p0#r1"]
    _write(layer, rec("p0", [item("p0#r0", True, sua="khác"), item("p0#r1", True)]))  # sau merge: khớp hoàn toàn
    assert relabel.staged_unmerged() == []


def test_build_refuses_to_delete_stage_with_unmerged_decisions(dirs, monkeypatch):
    stage, layer = dirs
    _write(layer, rec("p0", [item("p0#r0", False)]))
    _write(stage, rec("p0", [item("p0#r0", True)]))                       # quyết định chưa merge
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.iterdir()}
    monkeypatch.setattr(relabel, "plan", lambda cfg=None: [])
    with pytest.raises(SystemExit) as e:
        relabel.build()
    assert "chưa merge" in str(e.value) and "--force" in str(e.value)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.iterdir()} == before  # thư mục tạm còn nguyên
    relabel.build(dry_run=True)                                           # dry-run không bao giờ xóa
    assert stage.exists()
    relabel.build(force=True)                                             # --force: được xóa và dựng lại
    assert not stage.exists()


def test_build_allows_rebuild_when_everything_merged(dirs, monkeypatch):
    stage, layer = dirs
    it = item("p0#r0", True)
    _write(layer, rec("p0", [it]))
    _write(stage, rec("p0", [it]))
    monkeypatch.setattr(relabel, "plan", lambda cfg=None: [])
    assert relabel.staged_unmerged() == []
    relabel.build()
    assert not stage.exists()


def test_merge_back_dry_run_does_not_write_layer(dirs, monkeypatch):
    stage, layer = dirs
    _write(layer, rec("p0", [item("p0#r0", False)]))
    _write(stage, rec("p0", [item("p0#r0", True, sua="đã duyệt")]))
    before = {p.name: p.read_bytes() for p in layer.iterdir()}
    monkeypatch.setattr(relabel, "merge_from", lambda other, corr, cfg=None: {"cho_nhan_ve": 1, "dir_la_ban_sao": corr != layer})
    out = relabel.merge_back(dry_run=True)
    assert out["corrected"]["cho_nhan_ve"] == 1 and out["corrected"]["dry_run"] and out["corrected"]["dir_la_ban_sao"]
    assert {p.name: p.read_bytes() for p in layer.iterdir()} == before

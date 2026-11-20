"""Bộ lọc mặc định + theo câu hỏi. Tái sử dụng qdrant_store.build_filter (IsNullCondition, khoa_matches); KHÔNG viết lại logic khóa."""
from __future__ import annotations

from qdrant_client import models

from rag.embedding.qdrant_store import build_filter
from rag.retrieval.query_parser import ParsedQuery


def build_filters(pq: ParsedQuery, defaults: dict) -> tuple[models.Filter | None, dict]:
    """Trả (filter Qdrant, dict bộ lọc đã áp dụng để hiển thị/debug). Nhiều khóa -> chunk khớp BẤT KỲ khóa nào."""
    status, in_scope = defaults.get("status"), defaults.get("in_scope")
    bac = pq.bac_dao_tao or defaults.get("bac_dao_tao")
    ks = pq.khoa_list
    applied = {"status": status, "in_scope": in_scope, "bac_dao_tao": bac, "khoa": pq.khoa,
               "nguon": {"bac_dao_tao": pq.flags.get("bac_dao_tao", "mac_dinh"), "khoa": pq.flags.get("khoa")}}
    if len(ks) <= 1:
        return build_filter(status, in_scope, khoa=ks[0] if ks else None, bac_dao_tao=bac), applied
    base = build_filter(status, in_scope, khoa=None, bac_dao_tao=bac)
    any_k = models.Filter(should=[build_filter(None, None, khoa=k) for k in ks])
    return models.Filter(must=[*(base.must if base else []), any_k]), applied

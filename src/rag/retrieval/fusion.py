"""RRF phía client (minh bạch, cấu hình được) và khử trùng lặp theo sha256(embed_text).
Ghi chú: Qdrant có fusion RRF sẵn (Prefetch + FusionQuery); có thể so sánh với bản này ở bước đánh giá."""
from __future__ import annotations

import hashlib


def rrf(rankings: dict[str, list[str]], rrf_k: int = 60) -> list[tuple[str, float]]:
    """rankings: {tên retriever: [id theo thứ hạng 1..n]}. score = sum 1/(rrf_k + rank). Trả [(id, score)] giảm dần (hòa: id xuất hiện sớm hơn)."""
    score: dict[str, float] = {}
    first: dict[str, int] = {}
    for lst in rankings.values():
        for rank, pid in enumerate(lst, 1):
            score[pid] = score.get(pid, 0.0) + 1.0 / (rrf_k + rank)
            first.setdefault(pid, len(first))
    return sorted(score.items(), key=lambda x: (-x[1], first[x[0]]))


def text_key(embed_text: str) -> str:
    return hashlib.sha256(embed_text.encode("utf-8")).hexdigest()


def dedup(cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """cands đã xếp hạng (tốt nhất trước). Giữ bản đầu tiên của mỗi embed_text giống hệt nhau.
    Trả (danh sách đã khử trùng, [{kept: chunk_id, dropped: [chunk_id...]}])."""
    kept: dict[str, dict] = {}
    dropped: dict[str, list[str]] = {}
    for c in cands:
        k = text_key(c["payload"]["embed_text"])
        if k in kept:
            dropped.setdefault(k, []).append(c["chunk_id"])
        else:
            kept[k] = c
    dups = [{"kept": kept[k]["chunk_id"], "dropped": v} for k, v in dropped.items()]
    return list(kept.values()), dups


def fuse_with_rerank(pool: list[dict], rerank_scores: list[float], pq, w: float, struct_bonus: float, k: int = 60) -> list[dict]:
    """Kết hợp điểm cho mode hybrid_rerank_fused.

    pool: ứng viên sau RRF + khử trùng lặp, THEO THỨ TỰ RRF (rank_rrf = vị trí + 1); rerank_scores song song với pool.

        rank_rerank = hạng theo điểm rerank (giảm dần, 1 = tốt nhất)
        rank_score(r) = 1 / (k + r)                       (k = 60)
        final = w * rank_score(rank_rerank) + (1 - w) * rank_score(rank_rrf) + struct_bonus * n_match

    n_match = số thuộc tính (học kỳ, năm học, mã học phần, khóa) đã trích từ câu hỏi mà tiêu đề tài liệu (title/doc_heading) chứa đúng.
    Trả danh sách mới (đã gắn rerank, rank_rerank, rank_rrf, n_match, struct, fused) xếp theo final giảm dần.
    """
    from rag.retrieval.structure import title_matches
    order = sorted(range(len(pool)), key=lambda i: -rerank_scores[i])
    rank_rerank = {i: r for r, i in enumerate(order, 1)}
    out = []
    for i, c in enumerate(pool):
        hit = title_matches(c["payload"], pq)
        final = w / (k + rank_rerank[i]) + (1 - w) / (k + i + 1) + struct_bonus * len(hit)
        out.append({**c, "rerank": rerank_scores[i], "rank_rerank": rank_rerank[i], "rank_rrf": i + 1, "struct": hit, "n_match": len(hit), "fused": final})
    return sorted(out, key=lambda c: -c["fused"])

"""Nạp dữ liệu THỬ vào Qdrant để /search có kết quả trong lúc chờ T3-01..T3-03.

!!! Chỉ dùng tạm cho phát triển: chia đoạn rất đơn giản (theo đoạn văn, ~1500 ký tự,
overlap 15%). Pipeline chính thức (cắt theo Chương/Điều/Khoản, metadata đầy đủ) do Duy Anh
làm ở T3-01/T3-02/T3-03; khi có thì KHÔNG cần script này nữa.

Ví dụ:
    # trong container
    docker compose exec api python scripts/seed_qdrant.py --input /data/crawl_2/crawl_v2.json
    # trên máy (Qdrant chạy ở localhost:6333)
    python scripts/seed_qdrant.py --input ../crawl_2/crawl_v2.json
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client.http import models as qm  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.retrieval.embedder import build_embedder  # noqa: E402
from app.retrieval.qdrant_retriever import build_qdrant_client  # noqa: E402


def split_text(text: str, max_chars: int, overlap: float) -> list[str]:
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > max_chars:  # đoạn quá dài: cắt cứng
            head, p = p[:max_chars], p[max_chars:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if cur and len(cur) + len(p) + 1 > max_chars:
            chunks.append(cur)
            tail = cur[-int(max_chars * overlap):] if overlap > 0 else ""
            cur = (tail + "\n" + p).strip()
        else:
            cur = (cur + "\n" + p).strip()
    if cur:
        chunks.append(cur)
    return chunks


def build_chunks(records: list[dict], max_chars: int, overlap: float) -> list[dict]:
    out = []
    for r in records:
        body = "\n".join(x for x in (r.get("content"), r.get("extracted_text")) if x)
        text = (r.get("title") or "") + "\n" + body
        for i, piece in enumerate(split_text(text, max_chars, overlap)):
            out.append(
                {
                    "chunk_id": f"{r['id']}#{i}",
                    "doc_id": r["id"],
                    "text": piece,
                    "title": r.get("title"),
                    "source_url": r.get("source_url"),
                    "category": r.get("category"),
                    "doc_type": r.get("content_type"),
                    "issued_date": r.get("date") or None,
                    "chunk_index": i,
                    "pipeline": "seed_qdrant (tạm)",
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="crawl_v2.json hoặc crawl_v2_clean.json")
    ap.add_argument("--max-chars", type=int, default=1500)
    ap.add_argument("--overlap", type=float, default=0.15)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--recreate", action="store_true", help="Xóa collection cũ rồi tạo lại")
    args = ap.parse_args()

    s = get_settings()
    records = json.loads(Path(args.input).read_text(encoding="utf-8"))
    chunks = build_chunks(records, args.max_chars, args.overlap)
    print(f"{len(records)} bản ghi -> {len(chunks)} chunk")

    embedder = build_embedder(s)
    client = build_qdrant_client(s)
    print(f"Mô hình: {embedder.name} ({embedder.dim} chiều) | Qdrant: {s.qdrant_url} / {s.qdrant_collection}")

    if args.recreate and client.collection_exists(s.qdrant_collection):
        client.delete_collection(s.qdrant_collection)
    if not client.collection_exists(s.qdrant_collection):
        client.create_collection(
            s.qdrant_collection,
            vectors_config=qm.VectorParams(size=embedder.dim, distance=qm.Distance.COSINE),
        )
        for field in ("category", "doc_id"):
            client.create_payload_index(s.qdrant_collection, field, qm.PayloadSchemaType.KEYWORD)

    for start in range(0, len(chunks), args.batch):
        batch = chunks[start : start + args.batch]
        vecs = embedder.embed_passages([c["text"] for c in batch])
        client.upsert(
            s.qdrant_collection,
            points=[
                qm.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["chunk_id"])), vector=v, payload=c)
                for c, v in zip(batch, vecs)
            ],
        )
        print(f"  đã nạp {min(start + args.batch, len(chunks))}/{len(chunks)}")
    print("Xong. Thử: GET /api/v1/search?q=học phí")


if __name__ == "__main__":
    main()

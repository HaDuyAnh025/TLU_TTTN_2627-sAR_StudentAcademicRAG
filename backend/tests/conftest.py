"""Cấu hình test: SQLite trong bộ nhớ + Qdrant trong bộ nhớ + embedding giả lập.
Không cần Docker, không cần tải mô hình."""

import os

# Phải đặt TRƯỚC khi import app (Settings được cache)
os.environ.update(
    DATABASE_URL="sqlite://",
    QDRANT_URL=":memory:",
    QDRANT_COLLECTION="test_chunks",
    EMBEDDING_PROVIDER="hash",
    EMBEDDING_DIM="256",
    REDIS_URL="",
    MOCK_STREAM_DELAY_MS="0",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from qdrant_client.http import models as qm  # noqa: E402

from app.api import deps  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE_CHUNKS = [
    {"chunk_id": "tb-2248#0", "doc_id": "tb-2248", "category": "hoc_phi",
     "title": "Mức thu học phí đại học chính quy năm học 2026 - 2027",
     "source_url": "https://thanglong.edu.vn/vi/thong-bao/2248",
     "text": "Mức thu học phí đại học chính quy năm học 2026 - 2027 tính theo tín chỉ."},
    {"chunk_id": "tb-2281#0", "doc_id": "tb-2281", "category": "quy_che",
     "title": "Quy chế đào tạo trình độ đại học",
     "source_url": "https://thanglong.edu.vn/vi/thong-bao/2281",
     "text": "Điều kiện xét công nhận tốt nghiệp: tích lũy đủ số tín chỉ, chuẩn đầu ra ngoại ngữ.",
     "section": "Điều 32"},
    {"chunk_id": "tb-2277#0", "doc_id": "tb-2277", "category": "quy_che",
     "title": "Đăng ký học học kỳ I năm học 2026 - 2027",
     "source_url": "https://thanglong.edu.vn/vi/thong-bao/2277",
     "text": "Sinh viên đăng ký học qua Cổng thông tin sinh viên theo lịch từng khóa."},
]


class FakeCache:
    """Thay Redis trong test."""

    def __init__(self):
        self.store = {}

    enabled = True

    def get_json(self, key):
        return self.store.get(key)

    def set_json(self, key, value, ttl):
        self.store[key] = value

    def ping(self):
        return "ok"


@pytest.fixture(autouse=True)
def _db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def fake_cache():
    cache = FakeCache()
    app.dependency_overrides[deps.get_cache] = lambda: cache
    yield cache
    app.dependency_overrides.pop(deps.get_cache, None)


@pytest.fixture
def seeded_qdrant():
    client = deps.get_qdrant_client()
    embedder = deps.get_embedder()
    name = "test_chunks"
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(name, vectors_config=qm.VectorParams(size=embedder.dim, distance=qm.Distance.COSINE))
    vecs = embedder.embed_passages([c["title"] + "\n" + c["text"] for c in SAMPLE_CHUNKS])
    client.upsert(name, points=[qm.PointStruct(id=i, vector=v, payload=c)
                                for i, (c, v) in enumerate(zip(SAMPLE_CHUNKS, vecs))])
    yield client
    client.delete_collection(name)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

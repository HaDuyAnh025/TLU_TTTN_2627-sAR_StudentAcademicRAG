import json
import uuid

API = "/api/v1"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ready(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    checks = r.json()["checks"]
    assert checks["postgres"] == "ok" and checks["redis"] == "disabled"


# ---------- /chat + /conversations ----------


def test_chat_creates_conversation_and_history(client):
    r = client.post(f"{API}/chat", json={"message": "  Điều kiện tốt nghiệp là gì?  ", "top_k": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "mock"
    assert "Điều kiện tốt nghiệp là gì?" in body["answer"]
    assert [c["rank"] for c in body["citations"]] == [1, 2]

    conv_id = body["conversation_id"]
    r2 = client.post(f"{API}/chat", json={"conversation_id": conv_id, "message": "Còn học phí?"})
    assert r2.status_code == 200 and r2.json()["conversation_id"] == conv_id

    h = client.get(f"{API}/conversations/{conv_id}").json()
    assert h["title"] == "Điều kiện tốt nghiệp là gì?"
    assert [m["role"] for m in h["messages"]] == ["user", "assistant", "user", "assistant"]
    assert h["messages"][0]["content"] == "Điều kiện tốt nghiệp là gì?"
    assert h["messages"][1]["id"] == body["message_id"]
    assert len(h["messages"][1]["citations"]) == 2
    assert h["messages"][0]["citations"] == []


def test_chat_unknown_conversation_404(client):
    r = client.post(f"{API}/chat", json={"conversation_id": str(uuid.uuid4()), "message": "hi"})
    assert r.status_code == 404


def test_chat_validation(client):
    assert client.post(f"{API}/chat", json={"message": "   "}).status_code == 422
    assert client.post(f"{API}/chat", json={"message": "x" * 2001}).status_code == 422
    assert client.post(f"{API}/chat", json={"message": "hi", "top_k": 0}).status_code == 422


def test_get_conversation_404(client):
    assert client.get(f"{API}/conversations/{uuid.uuid4()}").status_code == 404
    assert client.get(f"{API}/conversations/khong-phai-uuid").status_code == 422


def test_chat_stream_sse(client):
    with client.stream("POST", f"{API}/chat", json={"message": "Học phí?", "stream": True}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = "".join(r.iter_text())
    events = []
    for block in raw.strip().split("\n\n"):
        ev, data = block.split("\n", 1)
        events.append((ev.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    names = [e for e, _ in events]
    assert names[0] == "start" and names[-2:] == ["citations", "done"]
    tokens = "".join(d["delta"] for e, d in events if e == "token")
    done = events[-1][1]
    assert tokens == done["answer"]
    # tin nhắn stream cũng được lưu DB
    h = client.get(f"{API}/conversations/{done['conversation_id']}").json()
    assert h["messages"][-1]["id"] == done["message_id"]


# ---------- /feedback ----------


def test_feedback_create_update_and_show_in_history(client):
    chat = client.post(f"{API}/chat", json={"message": "Lịch thi?"}).json()
    r = client.post(f"{API}/feedback", json={"message_id": chat["message_id"], "rating": "up"})
    assert r.status_code == 201 and r.json()["rating"] == "up"

    r = client.post(f"{API}/feedback", json={"message_id": chat["message_id"], "rating": "down", "comment": "Sai"})
    assert r.status_code == 200 and r.json()["rating"] == "down"

    msgs = client.get(f"{API}/conversations/{chat['conversation_id']}").json()["messages"]
    assert msgs[1]["feedback"] == {"rating": "down", "comment": "Sai"}
    assert msgs[0]["feedback"] is None


def test_feedback_errors(client):
    chat = client.post(f"{API}/chat", json={"message": "Lịch thi?"}).json()
    user_msg_id = client.get(f"{API}/conversations/{chat['conversation_id']}").json()["messages"][0]["id"]
    assert client.post(f"{API}/feedback", json={"message_id": user_msg_id, "rating": "up"}).status_code == 422
    assert client.post(f"{API}/feedback", json={"message_id": str(uuid.uuid4()), "rating": "up"}).status_code == 404
    assert client.post(f"{API}/feedback", json={"message_id": chat["message_id"], "rating": "5"}).status_code == 422


# ---------- /suggestions ----------


def test_suggestions(client):
    items = client.get(f"{API}/suggestions?limit=6").json()["items"]
    assert len(items) == 6
    assert len({i["category"] for i in items}) == 6  # mỗi nhóm một câu

    fee = client.get(f"{API}/suggestions?category=hoc_phi").json()["items"]
    assert fee and all(i["category"] == "hoc_phi" for i in fee)
    assert client.get(f"{API}/suggestions?limit=0").status_code == 422


# ---------- /search ----------


def test_search_real_qdrant(client, seeded_qdrant, fake_cache):
    r = client.get(f"{API}/search", params={"q": "học phí năm học 2026 - 2027", "top_k": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False and len(body["results"]) == 2
    top = body["results"][0]
    assert top["doc_id"] == "tb-2248" and top["category"] == "hoc_phi"
    assert top["source_url"].endswith("/2248")

    again = client.get(f"{API}/search", params={"q": "học phí năm học 2026 - 2027", "top_k": 2}).json()
    assert again["cached"] is True and again["results"] == body["results"]


def test_search_category_filter_and_metadata(client, seeded_qdrant, fake_cache):
    r = client.get(f"{API}/search", params={"q": "tốt nghiệp", "category": "quy_che"}).json()
    assert r["results"] and all(x["category"] == "quy_che" for x in r["results"])
    grad = next(x for x in r["results"] if x["doc_id"] == "tb-2281")
    assert grad["metadata"]["section"] == "Điều 32"


def test_search_top_k_capped(client, seeded_qdrant, fake_cache):
    r = client.get(f"{API}/search", params={"q": "học", "top_k": 100}).json()
    assert r["top_k"] == 20


def test_search_without_collection_returns_503(client, fake_cache):
    r = client.get(f"{API}/search", params={"q": "học phí"})
    assert r.status_code == 503 and "collection" in r.json()["detail"]


def test_search_validation(client):
    assert client.get(f"{API}/search").status_code == 422
    assert client.get(f"{API}/search", params={"q": "   "}).status_code == 422


def test_openapi_contract(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/chat", "/api/v1/conversations/{conversation_id}", "/api/v1/feedback",
              "/api/v1/suggestions", "/api/v1/search"):
        assert p in paths

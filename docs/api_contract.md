# Hợp đồng API & dữ liệu (T3-07, T3-08)

Tài liệu để 3 thành viên (Duy Anh – dữ liệu/retriever, Đức Duy – embedding/LLM/prompt, Quang Bình – API/DB/UI) ghép code không bị lệch.

- File OpenAPI đầy đủ (máy đọc / import vào Postman): [`docs/openapi.json`](openapi.json)
- Khi chạy server, xem và thử trực tiếp tại: `http://localhost:8000/docs`
- Sinh lại `docs/openapi.json` sau khi sửa schema: `python backend/scripts/export_openapi.py`

## 1. Danh sách endpoint

Tiền tố chung: `/api/v1` (riêng `/health` ở gốc).

| Method | Đường dẫn | Mô tả | Trạng thái Tuần 3 |
|---|---|---|---|
| `GET` | `/health` | Kiểm tra API sống | Thật |
| `GET` | `/health/ready` | Kiểm tra kết nối Postgres, Qdrant, Redis (trả `503` nếu Postgres lỗi) | Thật |
| `POST` | `/api/v1/chat` | Gửi câu hỏi, lưu DB, trả câu trả lời + trích dẫn (hỗ trợ cả JSON và SSE `stream=true`) | **Mock** câu trả lời, **thật** phần lưu DB |
| `GET` | `/api/v1/conversations/{id}` | Lấy lịch sử hội thoại (tin nhắn + nguồn + feedback) | Thật |
| `POST` | `/api/v1/feedback` | Đánh giá câu trả lời (`up` / `down` + nhận xét) | Thật |
| `GET` | `/api/v1/suggestions` | Danh sách câu hỏi gợi ý theo chủ đề | Thật |
| `GET` | `/api/v1/search` | Tìm đoạn tài liệu trong Qdrant + cache Redis | **Thật** |

---

## 2. Chi tiết từng endpoint chính

### 2.1 `POST /api/v1/chat`

**Request:**
```json
{
  "conversation_id": null,
  "message": "Điều kiện xét tốt nghiệp là gì?",
  "user_id": "sv-a42123",
  "top_k": 5,
  "filters": { "categories": ["quy_che"] },
  "stream": false
}
```
- `conversation_id = null` (hoặc bỏ qua): tạo cuộc hội thoại mới. Lượt hỏi tiếp theo truyền lại `conversation_id` nhận được để nối vào cùng cuộc hội thoại.

**Response `200 OK` (khi `stream = false`):**
```json
{
  "conversation_id": "2c8b08a0-6e8b-4a33-9b8b-2d1a0d72a111",
  "message_id": "9f62f2b0-5d3d-4e92-8a7e-7b2e1c3a4567",
  "answer": "[MOCK] Đây là câu trả lời giả lập ... [1] [2].",
  "citations": [
    {
      "rank": 1,
      "chunk_id": "tb-2281#mock-0",
      "doc_id": "tb-2281",
      "title": "QUYẾT ĐỊNH Ban hành Quy chế đào tạo trình độ đại học...",
      "source_url": "https://thanglong.edu.vn/vi/thong-bao/2281",
      "snippet": "Quy chế quy định về tổ chức đào tạo...",
      "score": 0.82,
      "metadata": { "category": "quy_che", "issued_date": "2026-08-20" }
    }
  ],
  "created_at": "2026-11-06T07:50:00Z",
  "mode": "mock"
}
```

**Khi `stream = true` (chuẩn bị sẵn cho T4-08):** trả về `text/event-stream`, mỗi sự kiện theo khuôn:
```
event: start
data: {"conversation_id": "...", "message_id": "..."}

event: token
data: {"delta": "Điều kiện "}

event: citations
data: {"citations": [...]}

event: done
data: {<toàn bộ ChatResponse>}
```

### 2.2 `GET /api/v1/conversations/{conversation_id}`

Trả về cuộc hội thoại với mảng `messages` theo thứ tự thời gian; mỗi tin nhắn của `assistant` kèm sẵn `citations` và `feedback` (nếu sinh viên đã đánh giá). Không tồn tại → `404`.

### 2.3 `POST /api/v1/feedback`

```json
{
  "message_id": "9f62f2b0-5d3d-4e92-8a7e-7b2e1c3a4567",
  "rating": "up",
  "comment": "Đúng điều khoản trong quy chế"
}
```
- Lần đầu gửi: `201 Created`. Gửi lại cùng `message_id`: `200 OK` (cập nhật đánh giá cũ).
- Nếu `message_id` là tin nhắn của `user`: `422 Unprocessable Entity`.

### 2.4 `GET /api/v1/suggestions?limit=6&category=hoc_phi`

- Không truyền `category`: trả câu hỏi rải đều qua các nhóm (`dang_ky_hoc_phan`, `hoc_phi`, `tot_nghiep`, `hoc_bong`, `thu_tuc`, `lich_thi`).

### 2.5 `GET /api/v1/search?q=học+phí&top_k=5&category=hoc_phi`

**Response `200 OK`:**
```json
{
  "query": "học phí",
  "top_k": 5,
  "results": [
    {
      "chunk_id": "tb-2248#0",
      "doc_id": "tb-2248",
      "text": "QUYẾT ĐỊNH V/v Ban hành mức thu học phí đại học chính quy năm học 2026 - 2027...",
      "score": 0.84,
      "title": "QUYẾT ĐỊNH V/v Ban hành mức thu học phí đại học chính quy năm học 2026 - 2027",
      "source_url": "https://thanglong.edu.vn/vi/thong-bao/2248",
      "category": "hoc_phi",
      "metadata": { "doc_type": "announcement", "issued_date": "2026-07-09", "chunk_index": 0 }
    }
  ],
  "took_ms": 18,
  "cached": false
}
```
- Khi Qdrant chưa chạy hoặc chưa có collection `sar_chunks`: trả `503 Service Unavailable` kèm thông báo hướng dẫn, không crash.

---

## 3. Hợp đồng Payload trong Qdrant (cần thống nhất với Duy Anh – T3-02, T3-03)

Để `GET /api/v1/search` đọc đúng dữ liệu mà script index của Duy Anh nạp vào Qdrant, mỗi point trong collection `sar_chunks` cần có `payload` theo các khóa sau:

| Khóa trong `payload` | Kiểu | Bắt buộc | Ví dụ | Ghi chú |
|---|---|---|---|---|
| `chunk_id` | `str` | Có | `"tb-2281#12"` | Định danh ổn định của chunk |
| `doc_id` | `str` | Có | `"tb-2281"` | Trùng `id` trong `crawl_v2.json` |
| `text` | `str` | Có | `"Điều 32. Điều kiện xét..."` | Nội dung đoạn văn |
| `title` | `str` | Nên có | `"QUYẾT ĐỊNH Ban hành Quy chế..."` | Tiêu đề tài liệu |
| `source_url` | `str` | Nên có | `"https://thanglong.edu.vn/vi/thong-bao/2281"` | Link gốc để sinh viên bấm mở |
| `category` | `str` | Nên có | `"quy_che"` | Có payload index kiểu `KEYWORD` để lọc |
| Các khóa khác (`section`, `page`, `issued_date`, `version`, `doc_type`...) | bất kỳ | Tùy chọn | `"section": "Chương IV - Điều 32"` | API tự động gom hết vào trường `metadata` của kết quả |

> **Lưu ý về mô hình embedding (thống nhất với Đức Duy – T3-05):** biến `EMBEDDING_MODEL`, `EMBEDDING_QUERY_PREFIX` trong `.env` của API **phải trùng** với mô hình đã dùng khi nạp Qdrant. Nếu dùng họ E5 (`intfloat/multilingual-e5-*`) thì câu hỏi có tiền tố `"query: "`, đoạn văn có `"passage: "`; nếu đổi sang `BAAI/bge-m3` hoặc `keepitreal/vietnamese-sbert` thì đặt hai biến prefix này thành chuỗi rỗng `""`.

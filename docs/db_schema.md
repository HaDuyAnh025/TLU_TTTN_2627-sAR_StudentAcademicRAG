# Sơ đồ cơ sở dữ liệu (T3-07)

4 bảng trong PostgreSQL để lưu lịch sử hỏi đáp, nguồn trích dẫn của từng câu trả lời và đánh giá của sinh viên.

- Nguồn định nghĩa: [`backend/app/db/models.py`](../backend/app/db/models.py)
- Migration tạo bảng: [`backend/alembic/versions/0001_initial.py`](../backend/alembic/versions/0001_initial.py)

## 1. Sơ đồ quan hệ (ERD)

```mermaid
erDiagram
    conversations ||--o{ messages : "có nhiều"
    messages ||--o{ citations : "trích dẫn"
    messages ||--o| feedback : "được đánh giá"

    conversations {
        uuid id PK
        varchar(64) user_id "IX, nullable"
        varchar(255) title "lấy từ câu hỏi đầu tiên"
        jsonb metadata "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    messages {
        uuid id PK
        uuid conversation_id FK "IX, ON DELETE CASCADE"
        message_role role "user | assistant | system"
        text content
        varchar(100) model "nullable, chỉ có ở assistant"
        int latency_ms "nullable"
        int prompt_tokens "nullable"
        int completion_tokens "nullable"
        jsonb metadata "nullable (mode, filters...)"
        timestamptz created_at
    }

    citations {
        uuid id PK
        uuid message_id FK "IX, ON DELETE CASCADE"
        smallint rank "UQ(message_id, rank), 1..k"
        varchar(128) chunk_id "khớp payload Qdrant"
        varchar(128) doc_id "vd. tb-2281"
        varchar(500) title
        text source_url
        text snippet "đoạn văn dùng làm căn cứ"
        float score "điểm tương đồng / rerank"
        jsonb metadata "category, section, page..."
    }

    feedback {
        uuid id PK
        uuid message_id FK "UQ, ON DELETE CASCADE"
        smallint rating "CHECK rating IN (-1, 1)"
        text comment "nullable"
        timestamptz created_at
        timestamptz updated_at
    }
```

## 2. Giải thích thiết kế

| Bảng | Vì sao thiết kế như vậy |
|---|---|
| `conversations` | Gom các lượt hỏi–đáp của một phiên chat. `user_id` để trống được vì hiện chưa bắt buộc đăng nhập; có thể truyền mã phiên ở trình duyệt. |
| `messages` | Lưu cả câu hỏi (`role='user'`) và câu trả lời (`role='assistant'`). Các cột `model`, `latency_ms`, `prompt_tokens`, `completion_tokens` chuẩn bị sẵn cho Tuần 4 (T4-05 tích hợp LLM) để theo dõi chi phí và tốc độ. |
| `citations` | Mỗi câu trả lời của assistant có 0..k nguồn. `rank` (1, 2, 3...) khớp với ký hiệu `[1]`, `[2]` trong câu trả lời (T4-04). Lưu lại cả `snippet`, `title`, `source_url` tại thời điểm trả lời để dù sau này index lại Qdrant thì lịch sử hội thoại cũ vẫn hiển thị đúng đoạn đã trích. |
| `feedback` | Ràng buộc `UNIQUE(message_id)`: mỗi câu trả lời có một đánh giá; sinh viên bấm lại 👍/👎 thì cập nhật (`rating`: `1` = up, `-1` = down). API chỉ cho phép đánh giá tin nhắn có `role='assistant'`. |

Tất cả khóa ngoại đều có `ON DELETE CASCADE`: xóa một `conversation` sẽ tự xóa `messages`, `citations`, `feedback` thuộc về nó.

## 3. Lệnh làm việc với migration

Chạy trong thư mục `backend/`:

```bash
# Áp dụng mọi migration lên DB hiện tại (container api tự chạy lệnh này khi khởi động)
alembic upgrade head

# Kiểm tra models.py và migration có lệch nhau không
alembic check

# Khi sửa models.py, sinh migration mới
alembic revision --autogenerate -m "mo_ta_thay_doi"
```

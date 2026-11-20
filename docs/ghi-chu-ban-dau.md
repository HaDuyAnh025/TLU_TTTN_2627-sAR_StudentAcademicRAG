# Ghi chú ban đầu về RAG

> Ghi chú học tập lúc bắt đầu dự án, đã sắp xếp lại. Cấu trúc thư mục hiện tại xem trong [README](../README.md); mục 2 dưới đây là bản thiết kế sơ khai ban đầu.

## 1. Luồng xử lý tổng quát

```
LOAD → CHUNKING → EMBEDDING → RETRIEVAL → CONTEXT → GENERATE
```

Chi tiết:

```
raw (.txt, .md, .pdf)
   │ read
   ▼
Document = source + text
   ▼
Chunking (có overlap)
   ▼
Embedding
   ▼
VECTOR STORE = vectors + metadata
   ▼
Retrieval
   ▼
argsort theo điểm tương đồng → trả về:
   1. Đoạn chữ
   2. Tên file nguồn
   3. Điểm tương đồng
```

## 2. Cấu trúc thư mục sơ khai

```
data/       # Tài liệu và dữ liệu sau xử lý
    raw/            # Tài liệu gốc (.txt, .md, .pdf)
    processed/      # Vector store sinh ra tự động

src/        # Code RAG chính, có thể tái dùng
    rag/
        config.py
        loader.py
        chunker.py
        embedding.py
        vector_store.py
        llm.py

scripts/    # Lệnh chạy ingest và hỏi đáp
    ingest.py       # đưa tài liệu vào
    ask.py          # hỏi RAG

tests/      # Kiểm tra code còn chạy đúng (chạy offline)

notebooks/  # Nơi thử nghiệm, không phải core
```

Nguyên tắc:
- `scripts/` chỉ là "điểm bấm chạy".
- Phần lõi (core) nằm trong package `src/rag/`.

## 3. Môi trường ảo

Kích hoạt `.venv` trước khi cài thư viện (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 4. Lưu ý khi làm retrieval

1. Tài liệu và câu hỏi phải dùng **chung một mô hình embedding**.
2. Không đảo "nhãn tài liệu" với "nhãn câu hỏi".
3. Chuẩn hóa vector trước khi tính điểm cosine.
4. Luôn giữ **nội dung + nguồn + số thứ tự** đi chung với vector.
5. Tài liệu đổi thì chạy lại bước chuẩn bị (ingest).

## 5. Ba luật để model không tự bịa câu trả lời

1. Chỉ dùng ngữ cảnh.
2. Thiếu thì nói "không tìm thấy".
3. Trích lại tên file nguồn.

## 6. Khung câu hỏi (user prompt)

Ghép ngữ cảnh và câu hỏi với nhau:

```python
RAG_PROMPT_TEMPLATE = """NGỮ CẢNH:
{context}

CÂU HỎI: {question}

Hãy trả lời câu hỏi dựa trên NGỮ CẢNH ở trên."""
```

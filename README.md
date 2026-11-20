# sAR – Chatbot RAG hỗ trợ học vụ

Hệ thống hỏi–đáp dựa trên kỹ thuật **RAG (Retrieval-Augmented Generation)**, giúp sinh viên tra cứu quy chế, thông báo, biểu mẫu và hướng dẫn học vụ. Câu trả lời luôn kèm **nguồn trích dẫn** (file / link / trang) và từ chối trả lời khi tài liệu không có thông tin.

> **Trạng thái:** đang trong giai đoạn thiết lập khung dự án. Cấu trúc thư mục đã có, các module đang được triển khai theo kế hoạch 10 tuần (xem mục [Lộ trình](#lộ-trình)).

## Mục tiêu

- Trả lời câu hỏi học vụ bằng tiếng Việt dựa trên tài liệu chính thức của trường.
- Trích dẫn nguồn cho mọi câu trả lời, hạn chế tối đa việc mô hình tự bịa (hallucination).
- Đo lường chất lượng bằng bộ câu hỏi chuẩn (50–100 câu) và các chỉ số RAGAS.

## Luồng xử lý

```
Nguồn (web, PDF, DOCX, HTML)
   │  crawl / load
   ▼
Document (text + nguồn)  ──►  làm sạch (bỏ header/footer, ký tự lạ)
   ▼
Chunking (overlap 10–20%) + metadata (nguồn, ngày, chương/mục, phiên bản)
   ▼
Embedding  ──►  Vector store (FAISS / Chroma / Qdrant)
   ▼
Retrieval (similarity + MMR, hybrid BM25 + vector) ──► Rerank
   ▼
Prompt (ngữ cảnh + câu hỏi) ──► LLM ──► Câu trả lời + nguồn trích dẫn
```

### Ba luật chống bịa câu trả lời

1. Chỉ dùng thông tin trong ngữ cảnh được truy xuất.
2. Thiếu thông tin thì nói rõ “không tìm thấy”.
3. Luôn trích lại tên file/nguồn.

### Lưu ý kỹ thuật

- Tài liệu và câu hỏi phải dùng **cùng một mô hình embedding**.
- Chuẩn hóa vector trước khi tính cosine similarity.
- Luôn giữ **nội dung + nguồn + số thứ tự** đi cùng vector.
- Khi tài liệu thay đổi, chạy lại bước ingest/index.

## Cấu trúc thư mục

```
sAR/
├─ configs/              # Cấu hình có thể chỉnh (YAML), tách khỏi code
│   ├─ sources.yaml      #   nguồn cần crawl
│   ├─ chunking.yaml     #   kích thước chunk, overlap
│   ├─ embedding.yaml    #   mô hình embedding
│   ├─ retrieval.yaml    #   top_k, MMR, hybrid, reranker
│   └─ llm.yaml          #   nhà cung cấp LLM, tham số sinh
├─ data/
│   ├─ raw/              # Tài liệu gốc, giữ nguyên
│   ├─ interim/          # Text đã làm sạch
│   ├─ processed/        # Corpus sạch + chunks kèm metadata
│   ├─ index/            # Vector store (sinh tự động, không commit)
│   ├─ cache/            # Cache câu trả lời phổ biến
│   └─ eval/             # Bộ câu hỏi test + đánh giá của người dùng
├─ src/rag/              # Package lõi
│   ├─ config.py         #   nạp cấu hình từ configs/
│   ├─ ingestion/        #   crawler, loader, cleaner
│   ├─ chunking/         #   splitter, metadata
│   ├─ embedding/        #   embedder, vector_store
│   ├─ retrieval/        #   dense, BM25, hybrid, reranker
│   ├─ generation/       #   prompts, llm, guardrails
│   ├─ enhancement/      #   normalizer, query_rewriter, memory, cache
│   ├─ evaluation/       #   retrieval_metrics, ragas_eval, ablation
│   └─ pipeline.py       #   ghép toàn bộ: câu hỏi → câu trả lời + nguồn
├─ app/                  # Giao diện web (Streamlit/Gradio)
├─ scripts/              # Điểm chạy: ingest.py, ask.py (chỉ gọi vào src/rag)
├─ tests/                # Kiểm thử, chạy offline (mock embedding/LLM)
└─ docs/                 # Ghi chú, tài liệu kiến trúc, báo cáo
```

Nguyên tắc: **logic nằm trong `src/rag/`**, `scripts/` và `app/` chỉ là điểm gọi; cùng một `pipeline.py` phục vụ cả chatbot lẫn đánh giá để số đo phản ánh đúng hành vi thật.

## Cài đặt

Yêu cầu: Python 3.10+.

```powershell
# Tạo và kích hoạt môi trường ảo (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Cài thư viện (khi đã có requirements.txt)
pip install -r requirements.txt
```

Tạo file `.env` (không commit) để chứa khóa API, ví dụ:

```
OPENAI_API_KEY=...
```

## Cách dùng (dự kiến)

```powershell
# 1. Đưa tài liệu vào: load → làm sạch → chunk → embed → lưu index
python scripts/ingest.py

# 2. Đặt câu hỏi
python scripts/ask.py "Điều kiện để được xét tốt nghiệp là gì?"
```

Các tham số (kích thước chunk, mô hình embedding, top_k, reranker, LLM…) chỉnh trong thư mục `configs/`.

## Lộ trình

| Tuần | Nội dung | Thư mục chính |
|---|---|---|
| 1 | Thu nhập & chuẩn bị dữ liệu: xác định nguồn, crawl, tải PDF/DOCX/HTML, chuẩn hóa text | `ingestion/`, `data/raw`, `data/interim` |
| 2 | Chunking & metadata, xây bộ tài liệu sạch | `chunking/`, `data/processed` |
| 3 | Embedding + vector DB, benchmark tốc độ và chất lượng | `embedding/`, `data/index` |
| 4 | Retriever + rerank: similarity, MMR, hybrid BM25, so sánh trước/sau rerank | `retrieval/` |
| 5 | Prompt + LLM: trả lời có trích dẫn, guardrail chống hallucination | `generation/` |
| 6 | Cải thiện chất lượng: viết tắt/thuật ngữ, query rewriting, multi-query, memory, cache | `enhancement/` |
| 7 | Web UI: hiển thị nguồn, lịch sử hội thoại, nút feedback, gợi ý câu hỏi | `app/` |
| 8 | Đánh giá: 50–100 câu test; Precision@k, Recall@k, MRR; RAGAS; so sánh no-RAG vs RAG | `evaluation/`, `data/eval` |
| 9–10 | Báo cáo, tài liệu kiến trúc, demo, slide + video | `docs/` |

## Sản phẩm bàn giao

- Repo RAG pipeline (crawler + chunker + retriever + LLM)
- Vector DB + tài liệu đã index
- Chatbot web hoạt động end-to-end
- Bộ test 50–100 câu + báo cáo RAGAS
- Báo cáo đánh giá + slide demo
- Tài liệu kiến trúc + README

## Ghi chú

Ghi chú học tập ban đầu được lưu tại [docs/ghi-chu-ban-dau.md](docs/ghi-chu-ban-dau.md).

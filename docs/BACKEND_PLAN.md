# Kế hoạch backend (giai đoạn B0)

Tài liệu này là kết quả khảo sát **chỉ đọc** (chưa sửa/tạo file nào ngoài file này) và đề xuất kiến trúc `app/` để nối với `frontend/`.
Mọi thay đổi ngoài `app/` nằm ở **mục 4** để bạn duyệt trước (theo CLAUDE.md: chỉ sửa `app/` ở giai đoạn nối API và phải liệt kê trước).

Nguồn đối chiếu: [`docs/ui-design/PLAN.md`](ui-design/PLAN.md) (hợp đồng API), [`docs/ui-design/SPEC.md`](ui-design/SPEC.md) mục 6, mục "Phụ thuộc mock" trong [`frontend/README.md`](../frontend/README.md).

**Giới hạn của khảo sát:** Qdrant **không chạy** lúc khảo sát (`localhost:6333` không phản hồi) nên chưa kiểm tra được dữ liệu thật trong các collection; mọi nhận định về payload dựa trên file chunk `data/processed/chunks/*.jsonl` và code ghi payload (`make_payload`). Chưa chạy `pytest` và chưa gọi OpenAI.

---

## 0. Tóm tắt (đọc phần này trước)

1. **Phần "sinh câu trả lời" chưa tồn tại.** `src/rag/generation/{llm,prompts,guardrails}.py`, `src/rag/pipeline.py`, `src/rag/enhancement/*` đều **rỗng (0 byte)**; `configs/llm.yaml` cũng rỗng. Retrieval (dense + BM25 + RRF + rerank) thì **chạy được** nhưng `scripts/ask.py` tự ghi "CHƯA gọi LLM". Đây là phần việc lớn nhất của backend.
2. **Dữ liệu thật khác dữ liệu mock.** Kho hiện có 381 tài liệu trong `sar_c2` (6.941 chunk), `doc_id` là mã Google Drive dạng `drive-1-2ATgl…`, không phải 7 tài liệu như mock. Trang Tài liệu sẽ có hàng trăm dòng (frontend chưa phân trang).
3. **Payload Qdrant đủ cho Citation, không cần re-index.** Thiếu `file` (tên file) và `version`, nhưng `file` tra được từ `configs/doc_meta.yaml`, `version` quản lý trong SQLite của app. Đoạn trích trước/sau (`excerpt_before/after`) lấy từ `data/processed/docs/<doc_id>.txt` qua `char_start/char_end`.
4. **Rerank trên CPU quá chậm cho chat** (đo sẵn: 12–17 giây cho 20 ứng viên bằng torch; ONNX int8 đã export, 4–7 giây). Cần chọn cấu hình rerank cho API (câu hỏi 3).
5. **Ba hàm hiện có sẽ gây hại nếu dùng cho một tài liệu đơn lẻ:** `chunk_corpus(only=…)` (ghi đè file chunk FROZEN), `index_config` (xóa mọi điểm không có trong file chunk), `cleaner.run` (xóa toàn bộ `data/interim/clean`). Admin thêm/re-index tài liệu phải dùng hàm mới nhỏ, **không** gọi ba hàm này (mục 3.7).
6. **Chưa có ngưỡng "không tìm thấy nguồn".** Các `max_rerank_score` đo được đều ≥ 0.98 và chỉ gồm câu hỏi trong phạm vi; `data/eval/questions.jsonl` rỗng. Phải đo trên câu hỏi ngoài phạm vi ở B2 mới đặt được ngưỡng.
7. Đề xuất: FastAPI + SQLite (SQLModel) + JWT (PyJWT + bcrypt) + SSE bằng `StreamingResponse`, 4 bước B1–B4 (mục 5), và **9 câu hỏi cần bạn trả lời** (mục 6).

---

## 1. Khảo sát code RAG hiện có

Trạng thái: **chạy được** (đã có dữ liệu/kết quả chạy thật), **dở dang** (có code nhưng thiếu phần hoặc chưa nối), **rỗng** (file 0 byte).

### 1.1 Bảng hiện trạng

| Chức năng | File → hàm/lớp | Trạng thái | Ghi chú |
|---|---|---|---|
| Crawl web | `src/rag/ingestion/crawler.py` → `Crawler.run` (cấu hình `configs/sources.yaml`) | Chạy được | Playwright; đã tạo `data/raw/manifest.jsonl` và 417 PDF + 3 JPG trong `data/raw/files/`. Chỉ crawl theo danh sách trang/chủ đề, **không có hàm "lấy một URL"**. |
| Trích xuất PDF/OCR | `src/rag/ingestion/loader.py` → `Pipeline.process_pdf`, `process_image`, `run` | Chạy được | Trang có text layer dùng PyMuPDF; trang scan OCR bằng VietOCR (nền) + RapidOCR (đối chiếu số). Cấu hình `configs/ocr.yaml`. `run()` quét cả `data/raw/files/`, nhưng `process_pdf(path)` nhận đường dẫn bất kỳ nên dùng được cho một file. `Pipeline.__init__` nạp OCR engine ngay (nặng RAM). |
| OCR engine | `src/rag/ingestion/ocr_engines.py` → `TesseractEngine`, `RapidOcrEngine`, `EasyOcrEngine`, `VietOcrEngine`, `PaddleOcrVlEngine`, `build_engines` | Chạy được | VietOCR `vgg_seq2seq` ~9 giây/trang trên CPU. |
| Hiệu chỉnh OCR (LLM + người duyệt) | `src/rag/ingestion/corrections.py`, `corrections_ui.py`, `relabel.py`; `src/rag/evaluation/{llm_review,rescan,sample_audit}.py` | Chạy được (quy trình thủ công, nhiều bước) | Có người duyệt. **Không áp dụng tự động cho tài liệu admin tải lên.** |
| VLM đọc bảng | `src/rag/ingestion/table_vlm.py`, `vlm_ocr.py` (OpenAI `gpt-5.4-mini` hoặc Anthropic, theo `configs/ocr.yaml`) | Chạy được | Chỉ cho trang bảng của chương trình đào tạo; có UI duyệt. |
| Văn bản sạch | `src/rag/ingestion/cleaner.py` → `clean_page` (một trang), `run` (**cả kho**) | Chạy được | `run()` **xóa mọi `*.json` trong `data/interim/clean` rồi dựng lại**: không dùng cho một tài liệu. `clean_page` dùng riêng được. |
| Chunking | `src/rag/chunking/splitter.py` → `Chunker.c1/c2/c3`, `chunk_corpus`; `chunking/loader.py` → `build_document`, `iter_documents`; `chunking/metadata.py` → `DocMeta`, `ChunkMeta`, `load_doc_metas` | Chạy được | Cấu hình `configs/chunking.yaml` (tiktoken cl100k, tối đa 512 token). `chunk_corpus` mở file đầu ra chế độ `"w"`: chạy với `only=…` vào thư mục mặc định sẽ **ghi đè file chunk đã FROZEN**. `Chunker` dùng được trực tiếp cho một `Document` + `DocMeta`. |
| Embedding | `src/rag/embedding/openai_embedder.py` → `OpenAIEmbedder` (`text-embedding-3-small`, 1536 chiều; có cache SQLite `data/cache/embeddings`) | Chạy được | Khóa `OPENAI_API_KEY` đọc từ `.env`. |
| BM25 sparse | `src/rag/embedding/bm25.py` → `tokenize`, `doc_to_sparse`, `query_to_sparse` | Chạy được | Tokenizer pyvi; IDF do Qdrant áp (`Modifier.IDF`). Cần `avgdl` từ `data/index/bm25_stats.json`. |
| Lưu Qdrant | `src/rag/embedding/qdrant_store.py` → `ensure_collection`, `make_payload`, `upsert_points`, `sync_delete_stale_ids`, `build_filter`, `verify_collection` | Chạy được | Vector có tên `dense_small`, `dense_large`, sparse `bm25`. Collection: `sar_c1`, `sar_c2`, `sar_c3`, `sar_c2_novlm` (`configs/embedding.yaml`). |
| Index | `src/rag/embedding/indexer.py` → `run_index`, `index_config`, `run_sparse_only`, `smoke`, `verify_filters` | Chạy được | Theo cả file chunk + kiểm FROZEN. `index_config` gọi `sync_delete_stale_ids` ⇒ **xóa mọi điểm không có trong file chunk**. |
| Retrieval | `src/rag/retrieval/retriever.py` → `Retriever.retrieve`, `first_stage`; `dense.py`, `sparse.py`, `fusion.py` (`rrf`, `dedup`, `fuse_with_rerank`), `filters.py`, `query_parser.py`, `structure.py`, `context.py` (`build_context`) | Chạy được | 5 chế độ: `dense`, `bm25`, `hybrid`, `hybrid_rerank`, `hybrid_rerank_fused`. Trả `RetrievalResult` có `final`, `context`, `max_rerank_score`. **Không có bộ lọc theo `doc_id`** (cần cho "Thử truy xuất" ở trang A3). |
| Rerank | `src/rag/retrieval/reranker.py` → `TorchReranker`, `OnnxReranker`, `make_reranker`, `get_reranker` (singleton); `onnx_export.py` | Chạy được | `BAAI/bge-reranker-v2-m3`; đã có `data/cache/hf/onnx/bge-reranker-v2-m3-int8.onnx` (0,57 GB). |
| Đo retrieval | `src/rag/retrieval/quick_eval.py`, `scripts/ask.py`, `scripts/bench_rerank.py` | Chạy được | Kết quả: `data/eval/retrieval_quick_eval.md`, `data/eval/rerank_bench/*.json`. |
| **Sinh câu trả lời LLM** | `src/rag/generation/llm.py`, `prompts.py`, `guardrails.py`; `configs/llm.yaml` | **Rỗng** | Chưa có prompt, chưa có client LLM, chưa có guardrail, chưa có ngưỡng từ chối. |
| **Pipeline hỏi → đáp** | `src/rag/pipeline.py` | **Rỗng** | README nói đây là điểm ghép dùng chung cho chatbot và đánh giá. |
| Cải thiện câu hỏi / bộ nhớ / cache | `src/rag/enhancement/{normalizer,query_rewriter,memory,cache}.py` | **Rỗng** | Câu hỏi tiếp nối kiểu "Học phí kỳ này?" chưa được viết lại thành câu độc lập. |
| Đánh giá RAGAS / ablation / metric | `src/rag/evaluation/{ragas_eval,ablation,retrieval_metrics}.py`; `data/eval/questions.jsonl` | **Rỗng** (file `.py` 0 byte; `questions.jsonl` 0 dòng) | Chưa có bộ câu hỏi chuẩn. |
| Test | `tests/test_*.py` (13 file, ~120 hàm test) | Có, **chưa chạy trong khảo sát** | Phủ chunking, embedding (có fake), retrieval (có fake). Không có test cho `app/`, LLM, pipeline. |
| Hạ tầng | `deploy/qdrant/docker-compose.yml` (Qdrant `v1.20.0`, cổng 6333/6334, lưu ở `data/index/qdrant`); `deploy/*.sh`, `deploy/pack.py`, `deploy/requirements-gpu.txt` | Docker đã cài (29.6.2) nhưng **container chưa chạy** | Collection đã có trên đĩa (`data/index/qdrant/collections`). |
| `app/` | — | Trống | |

### 1.2 Dữ liệu hiện có (đo từ file, không từ Qdrant)

- `c2_chunks.jsonl`: **6.941 chunk, 381 tài liệu** (`c1` 3.060; `c3` 6.941 + 290 parent; `c2_novlm` 1.089; `excluded_chunks.jsonl` 4.755 chunk ngoài phạm vi, **không được index**). Phân bố `doc_type` trong `c2`: `ctdt` 1.720, `hoc_phi` 1.770, `quy_che` 1.642, `thong_bao` 1.090, `ke_hoach` 436, `lich_thi` 213, `tkb` 47, `quy_trinh` 20, `hoc_bong` 3.
- 2.237/6.941 chunk là bảng (`is_table`); 15 chunk không có `page_start`; mọi chunk có `title` và `source_url`.
- `configs/doc_meta.yaml` có 417 tài liệu; `doc_id` = tên file bỏ đuôi (`chunking/loader.py → doc_id_of`), ví dụ `drive-1-2ATglHKBdlpCv7Qda6nUjbuQItzMOjf`. Mã chunk dạng `<doc_id>::s000`.
- **Bất thường cần kiểm khi bật Qdrant:** `data/index/bm25_stats.json` ghi `sar_c2.n_docs = 7004`, trong khi `c2_chunks.jsonl` (FROZEN) có 6.941 dòng. Có thể collection `sar_c2` còn là bản index cũ hơn bản chunk chốt. Việc đầu tiên của B1: bật Qdrant và chạy `verify_collection` (số điểm phải bằng 6.941, 0 điểm `in_scope=false`).

### 1.3 Hiệu năng rerank (đo sẵn trong `data/eval/rerank_bench/sweep.json`, CPU 10 nhân, RAM 16 GB)

| Backend | max_length | n ứng viên | Trung vị (giây) |
|---|---|---|---|
| torch | 512 | 20 (cấu hình mặc định hiện tại) | 16,8 |
| torch | 256 | 10 | 5,9 |
| onnx int8 | 512 | 20 | 9,2 |
| onnx int8 | 256 | 20 | 6,8 |
| onnx int8 | 256 | 10 | 4,0 |

Lần đo "mặc định" trong `threads.json` là 22–26 giây (lúc đó RAM trống chỉ ~1,8 GB). `retrieval_quick_eval.md` ghi rerank trung bình 46,9 giây (có lần nạp model). Kết luận: chưa dùng cấu hình mặc định cho chat được. Thứ hạng top-1 của ONNX lệch torch ở vài câu (`compare.json`), nên cần đo lại chất lượng trước khi chọn (B2).

---

## 2. Đối chiếu payload Qdrant ↔ trường frontend cần

Payload mỗi điểm = `ChunkMeta` trải phẳng + `chunk_id`, `config`, `embed_text`, `content`, `n_tokens` (`qdrant_store.make_payload`). Chỉ mục payload có sẵn: `doc_id`, `doc_type`, `status`, `in_scope`, `bac_dao_tao`, `khoa_tu`, `khoa_den`, `nganh`, `is_table`, `is_preamble`, `config`.

### 2.1 `Citation` (câu trả lời)

| Trường frontend | Lấy từ | Có sẵn? |
|---|---|---|
| `n` | thứ tự mục trong `context["items"]`, đánh số lại theo các nguồn thực sự được trích | Tính ở app |
| `doc_id`, `chunk_id` | payload `doc_id`, `chunk_id` | Có |
| `title` | payload `title` (không có chunk nào null) | Có |
| `type` (`pdf`/`web`) | suy ra: tài liệu có file PDF/ảnh trong `data/raw/files` ⇒ `pdf`. **Cả 381 tài liệu trong `sar_c2` đều là file PDF** (đã kiểm: 30 chunk có `doc_id` không bắt đầu bằng `drive` cũng thuộc một PDF `THÔNG-TIN-DANH-MỤC-NGÀNH-ĐÀO-TẠO_0001.pdf`); các trang web crawl (`data/raw/pages`) không có trong chỉ mục. Nên hiện chưa có trích dẫn nào mang `type="web"`. | Suy ra (quy ước cần bạn duyệt, câu hỏi 8) |
| `file` | `DocMeta.file` trong `configs/doc_meta.yaml` | **Không có trong payload**, tra bảng doc_meta khi khởi động (không cần re-index) |
| `url` | payload `source_url` | Có |
| `page` | `page_start` (và `page_end` nếu khác: "18–19") | Có (15 chunk null ⇒ hiện "—") |
| `loc` ("Chương 3 › Điều 14") | ghép từ `chapter`, `article`, `clause`, `section` (nhiều chunk null: 5.391 không có `chapter`, 2.505 không có `article`) hoặc phần breadcrumb đầu `embed_text` (`context.breadcrumb`) | Có, chất lượng không đồng đều |
| `excerpt_highlight` | payload `content` (văn bản chunk) | Có |
| `excerpt_before/after` | cắt `data/processed/docs/<doc_id>.txt` quanh `char_start/char_end` (±300 ký tự) | Có (đọc file, không cần re-index) |
| `rerank_score` | `c["rerank"]` (sigmoid của logit) | Có khi mode có rerank |

### 2.2 Tài liệu / chunk (trang quản trị)

| Trường frontend | Nguồn | Có sẵn? |
|---|---|---|
| `DocumentRow.title/file/category/type/version/status/updated_at` | `doc_meta.yaml` (+ `manifest.jsonl` cho ngày) + bảng `documents` trong SQLite | **`version` và `status` xử lý chưa có** ⇒ SQLite, không phải Qdrant |
| `chunks` (số chunk mỗi tài liệu) | `client.facet("sar_c2", key="doc_id")` một lần cho cả kho (có chỉ mục keyword) | Có |
| `Chunk.page/loc/tokens/is_table/text` | payload `page_start`, `loc` (như trên), `n_tokens`, `is_table`, `content`; sắp theo `chunk_index` | Có |
| `DocumentDetail.pages` | độ dài `data/processed/docs/<doc_id>.pages.json` hoặc `page_count` trong `data/interim/extract/*.json` | Có |
| `indexed_at` | `data/processed/embedding_usage.jsonl` (mức file) hoặc SQLite | Chỉ xấp xỉ cho tài liệu cũ |

### 2.3 Kết luận re-index

- **Không cần re-index** các collection hiện có để hiển thị Citation và trang quản trị.
- Chỉ re-index khi bước kiểm tra B1 phát hiện `sar_c2` lệch file chunk FROZEN (7004 so với 6941). Khi đó chạy `python scripts/ingest.py --stage index --config c2 --model small --yes` (embedding đã cache nên rất ít tốn OpenAI); bạn chạy hoặc xác nhận.
- Tùy chọn (không bắt buộc): với tài liệu **admin tải lên**, ghi thêm `file` và `version` vào payload lúc upsert (do app thêm khóa, không đi qua `ChunkMeta` vì nó `extra="forbid"`).

---

## 3. Kiến trúc đề xuất cho `app/`

Nguyên tắc (từ README): logic RAG nằm trong `src/rag/`, `app/` chỉ là lớp HTTP + lưu trữ + điều phối và **gọi lại** code có sẵn.

### 3.1 Cấu trúc thư mục

```text
app/
├─ __init__.py          # thêm <repo>/src vào sys.path (như scripts/*.py)
├─ main.py              # create_app(): lifespan (nạp DB, nối Qdrant, nạp reranker), CORS, include routers
├─ settings.py          # pydantic-settings: đọc .env (JWT, admin, CORS, đường dẫn DB, tên model LLM, ngưỡng)
├─ db.py                # engine SQLite (WAL), tạo bảng khi khởi động
├─ models.py            # SQLModel: Conversation, Message, Feedback, Document, Job
├─ schemas.py           # Pydantic: trùng với frontend/src/lib/types.ts (AnswerMessage, Citation, DocumentRow, ...)
├─ security.py          # JWT (PyJWT), bcrypt, rate-limit đăng nhập
├─ deps.py              # get_session, require_admin, get_rag
├─ routers/
│  ├─ health.py         # GET /api/health (Qdrant, DB, reranker đã nạp?)
│  ├─ chat.py           # POST /api/chat (SSE), POST /api/messages/{id}/regenerate (SSE)
│  ├─ conversations.py  # list / get / create / delete / delete-all
│  ├─ feedback.py       # POST /api/feedback
│  ├─ files.py          # GET /api/files/{doc_id}, GET /api/documents/{doc_id}/pages/{n}
│  ├─ admin_auth.py     # POST /api/admin/login
│  ├─ admin_documents.py# list/detail/add/reindex/delete/status/chunks/retrieve-test
│  └─ admin_feedback.py # list/patch/export.csv
└─ services/
   ├─ rag_service.py    # giữ Retriever + pipeline là singleton; khóa tuần tự cho rerank; chạy trong threadpool
   ├─ citations.py      # context → Citation[], parse [n], đánh số lại, cắt excerpt từ data/processed/docs
   ├─ conversations.py  # CRUD hội thoại/tin nhắn
   ├─ doc_registry.py   # nạp doc_meta.yaml + manifest → bảng documents; facet đếm chunk
   ├─ qdrant_admin.py   # scroll chunk theo doc_id, xóa/đổi status theo doc_id
   ├─ ingest_jobs.py    # hàng đợi nền 4 bước + cập nhật trạng thái
   └─ csv_export.py     # phan-hoi.csv (UTF-8 BOM)
```

`tests/` cho app: đề xuất `tests/test_app_*.py` dùng Retriever/LLM giả (mục 4.5).

### 3.2 Bảng endpoint (khớp hợp đồng frontend)

| Endpoint | Việc backend làm | Bước |
|---|---|---|
| `GET /api/health` | Kiểm tra DB, Qdrant, đã nạp reranker, `sar_c2` đủ điểm | B1 |
| `POST /api/admin/login` | So khớp `ADMIN_USERNAME`/`ADMIN_PASSWORD_HASH` (bcrypt) → JWT HS256, hạn 8 giờ; chặn thử mật khẩu liên tục | B1 |
| `POST /api/conversations` *(mới)* | Tạo hội thoại rỗng `{session_id}` → `{conversation_id, title, updated_at}` (thay `createConversation` chỉ-mock) | B1 |
| `GET /api/conversations?session_id=` · `GET /api/conversations/{id}?session_id=` · `DELETE …/{id}` · `DELETE …?session_id=` | Đọc/xóa theo `session_id`; kiểm quyền: `{id}` phải thuộc `session_id` gửi kèm | B1 |
| `POST /api/feedback` | Lưu/đổi đánh giá theo `message_id` (một đánh giá/tin nhắn); chụp lại `chunks` đã dùng từ `citations_json` của tin nhắn | B1 |
| `GET /api/admin/feedback?tab=` · `PATCH /api/admin/feedback/{id}` · `GET /api/admin/feedback/export.csv` | Danh sách + `stats` + `unhandled_wrong_count`; cập nhật `handled`/`in_test_set`; CSV UTF-8 BOM | B1 |
| `POST /api/chat` (SSE) | Luồng RAG đầy đủ (mục 3.4) | B2 |
| `POST /api/messages/{id}/regenerate` (SSE) | Chạy lại với cùng câu hỏi; thay tin nhắn cũ, xóa đánh giá cũ | B2 |
| `GET /api/files/{doc_id}?page=` | Trả file gốc (inline) từ `data/raw/files/<DocMeta.file>`; chỉ tài liệu `in_scope` và `hieu_luc` (sinh viên là công khai); chống path traversal | B2 |
| `GET /api/documents/{doc_id}/pages/{n}` *(mới)* | Văn bản trang `n` (từ `docs/<doc_id>.txt` + `pages.json`) cho `PdfViewerDialog` (khớp `PdfPagePreview` trong PLAN) | B2 |
| `GET /api/admin/documents?q&category&status` | Registry + `stats` + `total`; đếm chunk bằng `facet` | B3 |
| `GET /api/admin/documents/{id}` · `…/status` · `…/chunks?type&q&page&cursor` | Chi tiết, trạng thái 4 bước, chunk sắp theo `chunk_index` (scroll + lọc phía app) | B3 |
| `POST /api/admin/retrieve-test` | Chạy `Retriever` (có thêm lọc `doc_id`), trả top ứng viên kèm `rerank_score`; lỗi Qdrant ⇒ 503 + thông báo | B3 |
| `DELETE /api/admin/documents/{id}` · `POST …/{id}/reindex` | Xem mục 3.7 và câu hỏi 6 | B3 |
| `POST /api/admin/documents` (multipart hoặc JSON `{url}`) | Lưu file, tạo bản ghi + job nền 4 bước | B4 |

Mọi endpoint `/api/admin/*` (trừ login) bắt buộc `Authorization: Bearer <JWT>`; thiếu/hết hạn ⇒ 401.

### 3.3 Lưu trữ: SQLite + SQLModel

File `data/app/sar_app.sqlite` (`data/` đã nằm trong `.gitignore`). Bật `PRAGMA journal_mode=WAL`, một process uvicorn (không `--workers`).

| Bảng | Cột chính |
|---|---|
| `conversation` | `id` (uuid), `session_id` (index), `title`, `created_at`, `updated_at` |
| `message` | `id`, `conversation_id`, `question`, `answer`, `status` (`ok`/`no_source`), `citations_json`, `related_json`, `title`, `model`, `timings_json`, `created_at` |
| `feedback` | `id`, `message_id` (unique), `session_id`, `vote`, `reason`, `note`, `handled`, `in_test_set`, `created_at`, `updated_at` |
| `document` | `doc_id` (PK), `title`, `file`, `category` (= `doc_type`), `type` (`PDF`/`Web`/`Ảnh`), `origin` (`corpus`/`upload`), `status` (`indexed`/`processing`/`error`/`deleted`), `step`, `error_message`, `version`, `replaces_doc_id`, `pages`, `effective_date`, `url`, `sha256`, `created_at`, `updated_at`, `indexed_at` |

Khởi động lần đầu: nạp `document` từ `configs/doc_meta.yaml` + `manifest.jsonl` (`origin='corpus'`). Số chunk **không lưu**, luôn lấy từ Qdrant.

### 3.4 Luồng `POST /api/chat` (SSE)

Yêu cầu: `{session_id, conversation_id?, question}` (không có `conversation_id` thì tạo mới).

1. Kiểm tra câu hỏi (độ dài, không rỗng); nạp vài lượt gần nhất của hội thoại (nếu bật bộ nhớ, câu hỏi 7).
2. **Truy xuất** (`Retriever.retrieve`, collection `sar_c2`, bộ lọc mặc định `status=hieu_luc`, `in_scope=true`, `bac_dao_tao=dai_hoc`): embed câu hỏi (OpenAI, có cache) → dense + BM25 → RRF → khử trùng lặp → rerank → `top_k=5` → context theo ngân sách 1.500 token. Chạy trong threadpool, **tuần tự hóa phần rerank bằng một khóa** (một người dùng tại một thời điểm dùng model; người sau chờ, quá hạn ⇒ sự kiện `error` mã `busy`).
3. **Ngưỡng**: nếu `max_rerank_score` < `no_source_threshold` (cấu hình) hoặc `context` rỗng ⇒ trả ngay `done` với `status="no_source"`, `citations=[]`, câu trả lời chuẩn (không gọi LLM, tiết kiệm tiền, đúng luật chống bịa số 2).
4. **Sinh câu trả lời** (OpenAI chat, `stream=True`): prompt tiếng Việt gồm 3 luật chống bịa, context đánh số `[1]…[k]`, yêu cầu trích `[n]` ở cuối câu/ý; đoạn chữ nào về tới thì gửi sự kiện `delta`. Nếu mô hình trả dấu hiệu "không có thông tin" ⇒ `no_source`.
5. **Hậu xử lý** (`services/citations.py`): chỉ giữ các nguồn được trích, đánh số lại 1..N và sửa `[n]` trong văn bản; dựng `Citation[]` (mục 2.1). Không có nguồn nào được trích ⇒ coi là `no_source`.
6. **Câu hỏi liên quan** (3 câu): một lời gọi LLM ngắn không stream (câu hỏi 5) hoặc bỏ trống.
7. Lưu `message` + tiêu đề hội thoại (tạm: câu hỏi cắt 48 ký tự như mock) rồi gửi `done`.

Định dạng SSE (`Content-Type: text/event-stream`, frontend đọc bằng `fetch` + `ReadableStream`, **không** dùng `EventSource` vì là POST):

```text
event: status   data: {"stage": "retrieving" | "reranking" | "generating"}
event: delta    data: {"text": "..."}
event: done     data: <AnswerMessage JSON đầy đủ, gồm title và related_questions>
event: error    data: {"code": "retrieval_unavailable" | "llm_quota" | "llm_error" | "busy" | "internal", "message": "..."}
```

Lỗi giữa chừng gửi `error` rồi đóng luồng; frontend hiện khối lỗi "Thử lại" như thiết kế `02h`. Hủy từ phía client (đóng kết nối) phải dừng gọi LLM.

### 3.5 JWT admin, CORS, cấu hình

- **JWT:** PyJWT, HS256, `exp` 8 giờ, secret từ `JWT_SECRET`. Mật khẩu so khớp bằng `bcrypt` trực tiếp (không dùng `passlib`: `passlib 1.7.4` đã lâu không cập nhật và có báo cáo lỗi khi chạy với `bcrypt` ≥ 4.1; môi trường này đang cài `bcrypt 5.0.0`, tôi chưa tự kiểm lỗi đó). Rate-limit đăng nhập trong bộ nhớ (ví dụ 5 lần sai/10 phút/IP). Frontend đang lưu token ở `localStorage` (`sar_admin_token`); chấp nhận ở giai đoạn này, ghi nhận rủi ro XSS.
- **CORS:** `allow_origins = CORS_ORIGINS` (mặc định `http://localhost:3000`), `allow_headers` gồm `Authorization`, `Content-Type`; không dùng `*`.
- **Cấu hình:** `app/settings.py` (pydantic-settings) đọc `.env`; `OPENAI_API_KEY` vẫn do `rag` tự nạp qua `vlm_ocr._load_env`.
- **Chạy trên Windows:** `uvicorn app.main:app --host 127.0.0.1 --port 8000` từ thư mục gốc repo (không `--workers`; hạn chế `--reload` khi thử RAG vì mỗi lần reload nạp lại model). Đường dẫn có dấu cách/tiếng Việt: dùng `pathlib`, luôn `encoding="utf-8"`.

### 3.6 Ngưỡng điểm rerank → `no_source`

- Cấu hình `no_source_threshold` (xác suất sigmoid) trong `configs/retrieval.yaml`; giá trị khởi đầu **chưa chọn** vì dữ liệu hiện chỉ có điểm của câu hỏi trong phạm vi (0,98–0,997).
- B2 phải dựng bộ ≥ 30 câu (≥ 20 trong phạm vi có đáp án, ≥ 10 ngoài phạm vi như "thời tiết", "học phí trường khác"), đo `max_rerank_score` của hai nhóm, chọn ngưỡng tách được, và ghi kết quả vào `data/eval/`.
- Lớp bảo vệ thứ hai: prompt buộc LLM từ chối khi context không đủ (mục 3.4 bước 4).

### 3.7 Xử lý tài liệu nền 4 bước

Ánh xạ 4 bước giao diện (`Trích xuất → Chia chunk → Tạo embedding → Lưu Qdrant`) vào code có sẵn. Hàng đợi một luồng nền trong process (job lưu SQLite, khởi động lại thì job `processing` được xếp lại); bước 1 (OCR) nên chạy ở **tiến trình con** để không giữ RAM của VietOCR/torch trong server (câu hỏi 4).

| Bước | Tài liệu **tải lên mới** | Re-index tài liệu **có sẵn trong kho** |
|---|---|---|
| 1. Trích xuất | `Pipeline.process_pdf(path)` / `process_image(path)` (file lưu ở `data/uploads/<doc_id>.<ext>`) → JSON giống `data/interim/extract`; rồi `cleaner.clean_page` cho từng trang (không có lớp hiệu chỉnh ⇒ dùng text gốc) | **Bỏ qua** OCR: dùng lại `data/interim/clean/<tên>.json` (đã gồm hiệu chỉnh của người). Không chạy lại OCR vì sẽ mất các chỉnh sửa đã duyệt. |
| 2. Chia chunk | `build_document` + `Chunker(cfg, metas, aliases).c2(doc, DocMeta)` với `DocMeta` do app dựng (`doc_type` = danh mục, `bac_dao_tao` mặc định, `in_scope = doc_type != "khac"`, ngày hiệu lực…). Ghi `data/app/chunks/<doc_id>.jsonl` | Như bên trái nhưng `DocMeta` lấy từ `doc_meta.yaml` |
| 3. Embedding | `OpenAIEmbedder("small")`: `plan` → `embed_missing` → `get_vectors` (cache SQLite ⇒ re-index gần như miễn phí) | như nhau |
| 4. Lưu Qdrant | **Hàm mới** `upsert_document(rows)` (BM25 dùng `avgdl` đã lưu của `sar_c2`), rồi xóa điểm cũ của **đúng `doc_id` đó** | như nhau |

**Không dùng** `chunk_corpus`, `index_config`, `cleaner.run` cho một tài liệu (xem mục 0.5). Hai thay đổi trong `src/rag` để làm được việc này: hàm upsert/xóa theo `doc_id` và đường chunk một tài liệu (mục 4.2).

- `replace_existing`: tài liệu mới chỉ thay bản cũ **sau khi** xử lý xong (xóa điểm bản cũ, tăng `version`), giống mock.
- Lỗi: mỗi bước bắt ngoại lệ → `status="error"` + `error_message` tiếng Việt dễ hiểu (OCR không đọc được, hết quota OpenAI, Qdrant không phản hồi).
- Nguồn **đường link web**: chưa có hàm "lấy một URL" (`Crawler` chạy theo danh sách). Cần một hàm nhỏ mới (câu hỏi 9); để cuối B4.
- **Xóa tài liệu có sẵn trong kho:** đề xuất *xóa mềm* (đặt payload `status="het_hieu_luc"` bằng `set_payload`, không mất dữ liệu, hoàn tác được) thay vì xóa điểm; tài liệu tải lên thì xóa hẳn. Cần bạn quyết định (câu hỏi 6) vì lời hộp thoại hiện tại nói "xóa khỏi Qdrant".

---

## 4. Thay đổi cần làm ngoài `app/` (cần bạn duyệt)

### 4.1 `requirements.txt`

Hiện đã **cài trong môi trường** nhưng **chưa có trong file**: `fastapi 0.115.6`, `uvicorn 0.34.0`, `python-multipart 0.0.20`, `PyJWT 2.8.0`, `bcrypt 5.0.0`, `pydantic-settings 2.15.0`, `python-dotenv`, `httpx 0.28.1`, `SQLAlchemy 2.0.52`. **Chưa cài:** `sqlmodel`.

Đề xuất thêm: `fastapi`, `uvicorn[standard]`, `python-multipart`, `sqlmodel`, `PyJWT`, `bcrypt`, `pydantic-settings`, `httpx` (cho `TestClient`). Không thêm `passlib`/`python-jose`. Ghim phiên bản theo bản đang chạy được.

### 4.2 `src/rag/` (bổ sung nhỏ, không viết lại)

| File | Thêm gì |
|---|---|
| `generation/prompts.py` | Prompt hệ thống (3 luật chống bịa), mẫu ghép context đánh số, prompt tạo câu hỏi liên quan |
| `generation/llm.py` | Client OpenAI chat có `stream`, retry/timeout, đếm token, xử lý quota; tên model và tham số đọc từ `configs/llm.yaml` |
| `generation/guardrails.py` | Nhận diện từ chối, kiểm `[n]` hợp lệ, chuẩn hóa văn bản "không tìm thấy" |
| `pipeline.py` | `answer(question, user_ctx, history) → kết quả có citations + status`; dùng chung cho app và đánh giá |
| `retrieval/retriever.py`, `filters.py` | Tham số tùy chọn `doc_id` (thêm điều kiện `must` vào bộ lọc) cho "Thử truy xuất" |
| `embedding/qdrant_store.py`, `indexer.py` | `upsert_document(...)`, `delete_document(client, collection, doc_id)`, `set_document_status(...)`; tái dùng `make_payload`, `point_id`, `doc_to_sparse` |
| `chunking/` (hoặc `ingestion/single.py`) | `chunk_one(clean_json, DocMeta)` bọc `build_document` + `Chunker`, không ghi file FROZEN |
| `ingestion/` | `ingest_one(path)`: `Pipeline.process_pdf` + `clean_page` ghi vào thư mục của app (không đụng `data/interim/clean`). Tùy chọn: `fetch_url(url)` cho nguồn web |

### 4.3 `configs/`

- `llm.yaml` (đang rỗng): `provider`, `model`, `temperature`, `max_output_tokens`, `timeout_s`, `streaming`, `related_questions: {enabled, n}`.
- `retrieval.yaml`: thêm `no_source_threshold`, `api: {mode, config, rerank_backend, rerank_max_length, n_rerank, queue_timeout_s}`. (Không đổi các khóa đang dùng cho đánh giá.)
- **Không sửa** `doc_meta.yaml`, `chunking.yaml`, `embedding.yaml`, `FROZEN.md`. Tài liệu tải lên không ghi vào `doc_meta.yaml` mà nằm ở SQLite + `data/app/`.

### 4.4 `.env` / `.env.example`

`.env` hiện chỉ có `OPENAI_API_KEY`. Đề xuất tạo `.env.example` (đã được `.gitignore` cho phép) và bạn thêm vào `.env`:

```text
JWT_SECRET=<chuỗi ngẫu nhiên dài>
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<bcrypt, tạo bằng script app/scripts hoặc lệnh python>
CORS_ORIGINS=http://localhost:3000
APP_DB_PATH=data/app/sar_app.sqlite
UPLOAD_DIR=data/uploads
QDRANT_URL=http://localhost:6333
LLM_MODEL=<theo câu hỏi 1>
```

### 4.5 `tests/`

Thêm `tests/test_app_*.py` (không sửa test cũ): chat với Retriever và LLM giả (không gọi mạng), parse trích dẫn, ngưỡng `no_source`, JWT/đăng nhập, CRUD hội thoại, feedback, hàng đợi tài liệu với embedder giả.

### 4.6 `frontend/` (cần duyệt riêng khi tới từng bước)

Thay mock bằng gọi thật theo danh sách "phụ thuộc mock" của README:

Ghi chú: `client.facet` có trong `qdrant-client 1.20` đang cài (đã kiểm bằng `dir(QdrantClient)`, chưa chạy thử trên server).

| Thay đổi | Bước |
|---|---|
| `chat.service.ts`/`admin.service.ts` gọi HTTP qua `API_BASE`; chuyển bằng `NEXT_PUBLIC_USE_MOCK=false`; thêm client có `Authorization` và xử lý 401 → về `/admin/login` | B1 |
| Bỏ `createConversation` + `pending_question` chỉ-mock: gọi `POST /api/conversations`, giữ câu hỏi chờ trong `sessionStorage` | B1 |
| `chatStream` đọc SSE bằng `fetch` + `ReadableStream`, xử lý `status/delta/done/error`, hủy bằng `AbortController` | B2 |
| `PdfViewerDialog` gọi `/pages/{n}` thay vì dùng đoạn trích làm nội dung trang | B2 |
| Phân trang hoặc lọc phía server cho bảng tài liệu (hàng trăm dòng) | B3 |
| Polling `GET …/status` thay cho sự kiện `window`; `AddDocumentForm` gửi `File` (multipart) | B4 |
| Xóa tài khoản `admin/admin123` và `MockLoginError` khỏi đường chạy thật | B1 |

### 4.7 Hạ tầng

Bật Qdrant: `docker compose -f deploy/qdrant/docker-compose.yml up -d`. Không đổi file này.

---

## 5. Kế hoạch B1–B4

Mỗi bước kết thúc bằng: `pytest` xanh (test cũ + test mới), `npm run lint` và `npm run build` của frontend vẫn sạch, và bạn xem demo.

### B1 — Nền backend + hội thoại + phản hồi + đăng nhập admin (chưa có RAG)

- **Làm:** khung `app/`, settings, SQLite/SQLModel, CORS, `health`, JWT + `login`, hội thoại (kèm `POST /api/conversations`), `feedback`, `admin/feedback` (list/patch/CSV), bật Qdrant và **kiểm tra `sar_c2` (6.941 điểm)**; nối các service tương ứng của frontend.
- **Xong khi:** (a) `uvicorn` chạy cổng 8000, `GET /api/health` báo DB + Qdrant ổn; (b) đăng nhập admin thật, 401 khi sai/hết hạn; (c) frontend với `USE_MOCK=false` tạo/xóa hội thoại, gửi đánh giá, trang Phản hồi và badge sidebar chạy trên dữ liệu thật (chat vẫn mock); (d) CSV mở được trong Excel có đúng tiếng Việt; (e) kết quả `verify_collection` được ghi lại, và nếu lệch thì có quyết định re-index.

### B2 — Chat RAG thật

- **Làm:** `generation/*`, `pipeline.py`, `rag_service`, `citations`, SSE `/api/chat` và `regenerate`, ngưỡng `no_source`, câu hỏi liên quan, `files` + `pages/{n}`; cấu hình rerank cho API; frontend đọc SSE và `PdfViewerDialog` mới.
- **Xong khi:** (a) bộ ≥ 30 câu đã dựng (`data/eval/questions.jsonl`), ≥ 90% câu trong phạm vi trả `ok` kèm ít nhất một trích dẫn đúng tài liệu mong đợi, 100% câu ngoài phạm vi trả `no_source`; (b) mọi câu `ok` có `[n]` khớp `citations` (không có nguồn bịa); (c) độ trễ đo được: thời gian tới `delta` đầu tiên và tới `done` (mục tiêu ban đầu để bạn chốt: ≤ 10 giây tới chữ đầu tiên với cấu hình rerank đã chọn); (d) Qdrant/OpenAI lỗi ⇒ sự kiện `error` đúng mã, frontend hiện khối lỗi; (e) hủy giữa chừng dừng được lời gọi LLM.

### B3 — Quản trị tài liệu (đọc + xóa + re-index kho có sẵn)

- **Làm:** registry từ `doc_meta.yaml`, danh sách/chi tiết/stats (facet), chunk, thử truy xuất (lọc `doc_id`), xóa (mềm/cứng theo câu hỏi 6), re-index tài liệu có sẵn (bước 2–4), phân trang/lọc phía server ở frontend.
- **Xong khi:** (a) trang A2/A3 hiện đúng số liệu của 381 tài liệu (tổng chunk khớp `count` của Qdrant); (b) thử truy xuất trả kết quả có điểm rerank và hiện khối lỗi khi tắt Qdrant; (c) re-index một tài liệu có sẵn: số chunk trước/sau bằng nhau, kết quả hỏi đáp không đổi, cache embedding giúp tốn ~0 token; (d) xóa rồi (nếu mềm) khôi phục được, truy vấn không còn trả chunk của tài liệu đã xóa; (e) test xác nhận **không** có thao tác nào chạm file FROZEN.

### B4 — Tải tài liệu mới + xử lý nền

- **Làm:** nhận file (kiểm đuôi/dung lượng/mã băm), lưu `data/uploads`, hàng đợi nền 4 bước (OCR ở tiến trình con), trạng thái/bước/lỗi, `replace_existing` + `version`, polling ở frontend, gửi `multipart`; (cuối) nguồn đường link web.
- **Xong khi:** (a) tải một PDF có text layer: đủ 4 bước, hiện toast "Đã index xong", hỏi được và có trích dẫn đúng trang; (b) tải một PDF scan/ảnh: OCR chạy xong hoặc báo lỗi dễ hiểu; (c) khởi động lại server giữa chừng không làm treo bản ghi `processing`; (d) `replace_existing` thay bản cũ sau khi bản mới xong; (e) file sai định dạng/quá lớn bị từ chối ở backend (không chỉ ở giao diện); (f) hết quota OpenAI ⇒ `status=error` kèm lời nhắn rõ.

---

## 6. Câu hỏi cần bạn trả lời

1. **Mô hình sinh câu trả lời?** `configs/llm.yaml` đang rỗng. Gợi ý theo `configs/ocr.yaml`: OpenAI `gpt-5.4-mini` (đã có khóa `OPENAI_API_KEY`). Bạn muốn dùng mô hình nào, và có trần chi phí/ngày không?
2. **Chế độ truy xuất cho chat:** `hybrid_rerank` (đã được đo nhanh) hay `hybrid_rerank_fused` (w=0,7, đo thử có thứ hạng tốt hơn ở vài câu)? Collection dùng `sar_c2` đúng không?
3. **Rerank cho API:** chấp nhận ONNX int8 + `max_length` 256 + 10 ứng viên (~4 giây) đổi lại độ chính xác có thể giảm nhẹ, hay giữ torch (chậm hơn nhiều)? Bạn có GPU để chạy backend không (`deploy/HUONG_DAN_GPU.md` dành cho Ubuntu)?
4. **OCR cho tài liệu tải lên:** chạy ở tiến trình con (tách RAM, đề xuất) hay trong chính server? Chấp nhận **không có bước duyệt của người và không dùng VLM bảng** cho tài liệu tải lên (chất lượng bảng scan có thể thấp)?
5. **Câu hỏi liên quan và tiêu đề hội thoại:** dùng thêm một lời gọi LLM nhỏ cho mỗi câu trả lời (thêm ~1 giây và chi phí), hay tạm dùng gợi ý tĩnh và tiêu đề = câu hỏi cắt ngắn như mock?
6. **Xóa tài liệu có sẵn trong kho:** xóa mềm (đặt `het_hieu_luc`, hoàn tác được; đổi lời hộp thoại) hay xóa cứng khỏi Qdrant như mock? Còn tài liệu `in_scope=false` (không được index) có hiện ở trang Tài liệu không?
7. **Hội thoại nhiều lượt:** có cần viết lại câu hỏi tiếp nối ("Học phí kỳ này?") dựa vào lượt trước ở B2, hay để sau? (`enhancement/query_rewriter.py` và `memory.py` đang rỗng.)
8. **Quy ước `type` của trích dẫn:** mọi tài liệu đang index đều là file PDF và đều có `source_url` (trang thông báo gốc). Đề xuất: có file ⇒ `pdf` (nút "Xem PDF", kèm link trang gốc nếu muốn); `web` dành cho tài liệu tải lên từ đường link. Đồng ý không? (Nếu muốn, panel nguồn có thể hiện thêm nút "Mở trang thông báo gốc" từ `source_url`; đó là thay đổi frontend nhỏ.)
9. **Thêm tài liệu từ đường link:** có bắt buộc trong B4 không (cần viết hàm lấy một URL bằng Playwright, chưa có)? Và giá trị mặc định cho `bac_dao_tao`/khóa của tài liệu tải lên (đề xuất `dai_hoc`, không giới hạn khóa) có ổn không, hay cần thêm ô chọn trên form?

Ngoài ra cần bạn thực hiện/xác nhận: bật Qdrant bằng Docker, đặt `JWT_SECRET` và `ADMIN_PASSWORD_HASH` trong `.env`, và (ở B2) gắn nhãn đáp án cho ~20 câu hỏi trong phạm vi.

---

## 7. Rủi ro chính

| Rủi ro | Giảm thiểu |
|---|---|
| Độ trễ rerank/LLM làm chat chậm | ONNX + giảm ứng viên, hiện `status` trong SSE, đo ở B2 |
| Dùng nhầm hàm xử lý cả kho làm mất dữ liệu FROZEN/clean/Qdrant | Chỉ dùng hàm mới theo `doc_id`; test chặn ghi vào `data/processed/chunks` |
| Ngưỡng `no_source` sai ⇒ bịa hoặc từ chối nhầm | Bộ câu hỏi có nhóm ngoài phạm vi; hai lớp (ngưỡng + prompt) |
| Một worker uvicorn, một model rerank ⇒ nhiều người hỏi cùng lúc phải xếp hàng | Khóa tuần tự + `busy` có thông báo; chấp nhận cho đồ án/demo |
| `sar_c2` lệch file chunk FROZEN | Kiểm tra đầu B1, re-index (embedding cache) nếu lệch |
| Token admin ở `localStorage` | Chấp nhận giai đoạn này; hạn 8 giờ; về sau cân nhắc cookie `HttpOnly` |
| `session_id` không phải xác thực | Chỉ coi là định danh trình duyệt; kiểm quyền hội thoại theo `session_id`; không lưu dữ liệu nhạy cảm |
| Dữ liệu `data/` và `.env` không được commit | Đã có trong `.gitignore`; thư mục mới `data/app`, `data/uploads` nằm dưới `data/` |

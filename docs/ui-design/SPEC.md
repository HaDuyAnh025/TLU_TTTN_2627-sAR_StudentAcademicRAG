# Đặc tả giao diện — Trợ lý Học vụ (RAG tra cứu thông tin học vụ)

Đề tài: *Ứng dụng các kỹ thuật RAG để hỗ trợ sinh viên tra cứu thông tin học vụ* — Trường Đại học Thăng Long.
Tài liệu này mô tả **chính xác** giao diện cần dựng. Nguồn chuẩn để đối chiếu: ảnh trong `screenshots/` và bản chạy thử trong `prototype/`.

---

## 1. Phạm vi & nguyên tắc

- **Sinh viên không đăng nhập.** Lịch sử hội thoại lưu theo `session_id` (sinh ngẫu nhiên, lưu trong `localStorage`). Backend lưu hội thoại theo `session_id`.
- **Chỉ trang quản trị cần đăng nhập** (1 tài khoản admin, username/password → JWT).
- Ngôn ngữ giao diện: **tiếng Việt**. `<html lang="vi">`.
- Mỗi câu trả lời **bắt buộc kèm nguồn trích dẫn** (tên văn bản, Điều/Mục, trang hoặc link).
- Không tìm thấy nguồn phù hợp → **không bịa**, hiển thị trạng thái “Không tìm thấy nguồn phù hợp”.
- Mọi nút đều phải có phản hồi rõ ràng: **chuyển trang**, **mở hộp thoại**, hoặc **hiện thông báo (toast)** cho cả thành công lẫn lỗi. Form lỗi báo **ngay tại ô nhập**.
- Desktop-first, rộng thiết kế 1440px; phải dùng được ở màn hẹp (cột tự xuống dòng, bảng cuộn ngang trong khung).

## 2. Design tokens

Xem `design-tokens/tokens.css` (và `tokens.json`). Tóm tắt:

| Vai trò | Giá trị |
|---|---|
| Màu chính (navy Thăng Long) | `#000066` |
| Đỏ Thăng Long — **chỉ** điểm nhấn logo | `#F5250C` |
| Chữ / phụ / mờ | `#111827` / `#374151` / `#5B6472` |
| Nhãn overline | `#5B5A96`, 12px, 600, VIẾT HOA, letter-spacing 0.04em |
| Nền trang / bề mặt | `#F5F6F8` / `#FFFFFF` |
| Viền | `#E3E6EB` (mặc định), `#D5D9E0` (nút phụ), `#C9CED6` (ô nhập) |
| Lỗi | nền `#FEEDEB`, viền `#F7C4BC`, chữ `#B01C08`, nút xóa `#C81E0A` |
| Thành công | nền `#E7F5EE`, chữ `#166534`, toast `#0E5132` |
| Tô sáng đoạn trích | `#E6E5F4` |

- Font: **Be Vietnam Pro** 400/500/600/700 (file có sẵn trong `prototype/fonts/`, giấy phép OFL).
- Bo góc: 6 (số trích dẫn) · 8 (mục sidebar) · 10 (nút, input) · 12 (thẻ nguồn, toast) · 16 (thẻ trả lời, hộp thoại, ô hỏi).
- Chiều cao điều khiển: **44px** (tối thiểu cho vùng chạm); nút phụ nhỏ 40px.
- Focus: `outline: 2px solid #000066; outline-offset: 2px` cho button, a, input, textarea, select.
- Icon: nét (stroke) 2px, đầu tròn, 16–18px — tương đương bộ **Lucide/Feather** (book-open, message-square, search, plus, trash-2, info, thumbs-up, thumbs-down, copy, refresh-cw, send, file, globe, external-link, x, check, alert-circle, corner-down-right, upload, download, play, log-out, graduation-cap, credit-card, calendar, clipboard). Không dùng emoji.
- Logo: `assets/logo-mark.svg` (sách mở + kính lúp đỏ trên nền navy). Không dùng logo chính thức của trường trừ khi được phép.

## 3. Bố cục chung

**Màn sinh viên:** `[Sidebar 260px] [Khung chat co giãn, nội dung tối đa 760px, căn giữa] [Panel nguồn 340px — chỉ ở màn câu trả lời]`.
**Màn quản trị:** `[Sidebar 240px] [Nội dung co giãn, padding 32px]`.
Sidebar có viền phải 1px `#E3E6EB`, nền trắng; khi màn hẹp các cột xếp chồng.

### Sidebar sinh viên (dùng chung màn 1, 2)
1. Logo lockup: logo 40px + “Trợ lý Học vụ” (16/600) + “Đại học Thăng Long” (13, muted).
2. Nút chính “+ Cuộc trò chuyện mới” (full width).
3. Ô tìm “Tìm cuộc trò chuyện” (lọc lịch sử theo tên, có trạng thái rỗng).
4. Lịch sử nhóm theo **Hôm nay / 7 ngày trước / Tháng trước** (overline). Mục: icon chat + tên 1 dòng, cắt “…”. Mục đang mở: nền navy 10%, chữ navy đậm, `aria-current="page"`.
5. Chân: icon info + “Không cần đăng nhập. Lịch sử hội thoại chỉ được lưu trên trình duyệt này.” + nút phụ “Xóa toàn bộ lịch sử”.

### Sidebar quản trị (dùng chung A2–A4)
Logo lockup (dòng phụ “Quản trị”) · mục **Tài liệu** · mục **Phản hồi** (badge đỏ số phản hồi Sai chưa xử lý) · chân: “Mở trang sinh viên”, “Đăng xuất”.

## 4. Màn hình

Ảnh tham chiếu ghi trong ngoặc. Dữ liệu trong ảnh là **minh họa**; chỗ `[…]` là dữ liệu thật cần lấy từ backend.

### 1 · Màn hình chào — `/` (`01-welcome.png`)
- Tiêu đề 32/700 căn giữa: “Bạn cần tra cứu thông tin học vụ gì?” + mô tả 16px (tối đa 620px).
- Ô hỏi lớn (bo 18, viền `#C9CED6`), textarea 2 dòng + nút gửi vuông 44px nền navy.
- “GỢI Ý CÂU HỎI”: lưới 2 cột (auto-fit min 300px) gồm 4 thẻ danh mục — Quy chế & tốt nghiệp · Học phí & học bổng · Đăng ký học phần · Thủ tục hành chính. Mỗi thẻ: ô icon 32px nền navy 10% + tiêu đề + 3 câu hỏi (icon ↳, cao 44px, hover nền `#F1F3F6`). Bấm câu hỏi → gửi câu hỏi đó, sang màn 2.
- Dòng cuối: “Dữ liệu tra cứu: quy chế, quy định và thông báo đăng trên thanglong.edu.vn”.

### 2 · Câu trả lời + nguồn — `/c/:conversationId` (`02-answer-with-sources.png`)
**Header** (nền trắng, viền dưới): tên hội thoại 18/700 + “Câu trả lời dựa trên N nguồn…”; nút phụ “Xóa hội thoại”.
**Luồng chat:**
- Câu hỏi người dùng: bong bóng navy chữ trắng, căn phải, bo 16/16/4/16, rộng tối đa 80%.
- Thẻ trả lời (trắng, viền, bo 16, padding 24): avatar 32px (icon sách) + “Trợ lý Học vụ”; nội dung có danh sách đánh số; **số trích dẫn** dạng ô 24×24 bo 6 chèn cuối câu (mặc định nền navy 10% chữ navy; nguồn đang xem: nền navy chữ trắng). Bấm số → chọn nguồn đó ở panel phải.
- **NGUỒN TRÍCH DẪN (N)**: lưới thẻ nguồn (min 200px). Thẻ: số, tiêu đề 14/600, dòng meta có icon file/globe (“Điều 14 · Trang 18” hoặc tên miền). Thẻ đang chọn: viền navy, nền navy 10%, `aria-pressed`.
- **Thanh đánh giá** (viền trên): “Câu trả lời này có đúng không?” · nút **Đúng** (thumbs-up) · nút **Sai** (thumbs-down) · khoảng trống · **Sao chép** · **Tạo lại** (nút ghost).
- “CÂU HỎI LIÊN QUAN”: 3 chip gợi ý; bấm → điền vào ô hỏi + toast thông tin.
- Ô hỏi cố định cuối cột + dòng nhắc “Câu trả lời được tạo từ văn bản chính thức của trường. Hãy kiểm tra nguồn trích dẫn trước khi làm thủ tục.”

**Panel nguồn (phải):** “NGUỒN i / N” + badge loại (PDF/Trang web) · tiêu đề tài liệu 18/700 · tên file hoặc URL · khối “Vị trí | Trang” (nền `#F5F6F8`) · “Đoạn trích được dùng để trả lời” trong khung viền, **phần được dùng tô `#E6E5F4`** · nút chính “Xem PDF tại trang X” (PDF → hộp thoại xem PDF) hoặc “Mở trang web (tab mới)” (web → `target=_blank`) · ghi chú giải thích truy xuất + xếp hạng lại.

### Trạng thái của màn 2
| Trạng thái | Ảnh | Mô tả |
|---|---|---|
| Form báo Sai + lỗi kiểm tra | `02b-…` | Nút Sai đổi sang nền `#FEEDEB` viền đỏ. Form nền `#FFF6F5` viền `#F7C4BC`: “Câu trả lời sai ở đâu? Chọn một kiểu lỗi hoặc tự mô tả.” · 5 chip chọn 1: *Thông tin sai, Nguồn không liên quan, Thiếu thông tin, Thông tin đã cũ, Khác (tự nhập)* · textarea (nhãn đổi thành “Mô tả lỗi (bắt buộc)” khi chọn Khác) · Hủy / Gửi phản hồi. |
| Đã gửi báo Sai | `02c-…` | Thay hai nút bằng “✓ Đã gửi báo sai: <lý do>” (chữ đỏ) + link “Đổi đánh giá”; toast xanh “Đã gửi phản hồi”. |
| Đã đánh giá Đúng | `02d-…` | “✓ Bạn đã đánh giá: câu trả lời đúng” (chữ xanh) + “Đổi đánh giá”; toast “Cảm ơn bạn! Đã ghi nhận: câu trả lời này đúng.” |
| Xem PDF | `02e-…` | Hộp thoại 760px: tiêu đề + “file · Trang X”, nút ×; vùng xem nền `#E9ECF0` hiển thị trang PDF có đoạn tô sáng; chân: Tải PDF / Đóng. |
| Xác nhận xóa hội thoại | `02f-…` | Hộp thoại xác nhận, nút xóa đỏ; xác nhận → về màn 1. |
| Đang trả lời | (prototype) | Khung có spinner “Đang tìm trong tài liệu của trường và soạn câu trả lời…” + 3 thanh skeleton nhấp nháy. Nút gửi bị khóa. |
| Không tìm thấy nguồn | `02g-…` | Badge “Không tìm thấy nguồn phù hợp” + lời khuyên hỏi lại / liên hệ Phòng Đào tạo. Không có thanh nguồn. |
| Lỗi gửi câu hỏi | `02h-…` | Khối lỗi đỏ “Không gửi được câu hỏi do mất kết nối tới máy chủ.” + nút “Thử lại”; toast lỗi. |
| Tạo lại | (prototype) | Nội dung mờ 45%, nhãn “Đang tạo lại câu trả lời…”, nút Tạo lại xoay spinner và bị khóa; xong → toast. |

### A1 · Đăng nhập quản trị — `/admin/login` (`A1-…`, `A1b-…`)
Thẻ 420px căn giữa: logo + “Khu vực quản trị dữ liệu”; “Đăng nhập quản trị”; Tên đăng nhập, Mật khẩu (`autocomplete` đúng); nút navy full width; link “Bạn là sinh viên? Không cần đăng nhập — về trang tra cứu”. Lỗi: khung đỏ phía trên + viền đỏ ô thiếu (“Vui lòng nhập đầy đủ…” / “Tên đăng nhập hoặc mật khẩu không đúng…”).

### A2 · Quản lý tài liệu — `/admin/documents` (`A2-…`, `A2b-…`, `A2c-…`)
- Tiêu đề “Tài liệu” + mô tả; nút chính “+ Thêm tài liệu”.
- 4 thẻ số liệu: Tài liệu đã index · Tổng số chunk trong Qdrant · Đang xử lý (navy) · Lỗi xử lý (đỏ).
- **Form thêm tài liệu** (mở dưới thẻ số liệu, viền navy): tab *Tải file lên* (vùng kéo thả, PDF/PNG/JPG, liệt kê file + “Hợp lệ/Sai định dạng”) / *Từ đường link web* (URL phải bắt đầu http(s)://) · Tên hiển thị trong trích dẫn (tự điền từ tên file) · Danh mục (select) · Ngày hiệu lực · checkbox “bản mới thay thế tài liệu đã có” · dải 4 bước xử lý (Trích xuất PDF/OCR → Chia chunk → Tạo embedding → Lưu Qdrant kèm doc_id, version) · Hủy / “Xử lý & đưa vào index” (loading “Đang tải lên…”).
- Bộ lọc: tìm theo tên/file · danh mục · trạng thái. Không có kết quả → trạng thái rỗng + “Xóa bộ lọc”.
- Bảng (cuộn ngang khi hẹp): Tài liệu (tên link sang A3 + tên file) · Danh mục · Loại · Chunk · Trạng thái (badge *Đã index* xanh / *Đang xử lý* navy có spinner + “Bước k/4 · tên bước” / *Lỗi* đỏ + lý do) · Cập nhật · Thao tác (Re-index, Xóa — icon 40px, khóa khi đang xử lý).
- Xóa → hộp thoại “Xóa “<tên>”? N chunk sẽ bị xóa khỏi Qdrant… Không thể hoàn tác.” → toast.
- Trạng thái xử lý cập nhật trực tiếp (polling hoặc SSE) → xong toast “Đã index xong”, lỗi toast “Xử lý thất bại”.

### A3 · Chi tiết tài liệu — `/admin/documents/:docId` (`A3-…`, `A3b-…`)
Breadcrumb “Tài liệu › <tên>” · tiêu đề + badge loại + badge trạng thái (+ bước khi re-index) · nút Tải file gốc / Re-index (xác nhận) / Xóa (xác nhận, xong về A2).
Khối thông tin 6 ô: `doc_id` (monospace) · Phiên bản · Danh mục · Số trang · Số chunk · Index lúc.
Hai cột:
- **Chunk của tài liệu**: lọc Tất cả / Văn bản / Bảng · tìm nội dung · lọc theo trang · thẻ chunk (id monospace · trang · vị trí · badge “Bảng · 1 dòng = 1 câu” · số token; nội dung giữ xuống dòng) · “Xem thêm chunk (đang hiện x / tổng)”.
- **Thử truy xuất**: textarea câu hỏi (bắt buộc) · checkbox “Chỉ tìm trong tài liệu này” · nút “Chạy thử” (loading) · danh sách xếp hạng: số thứ tự, chunk id, trang, đoạn trích, thanh điểm rerank + số (2 chữ số thập phân) · ghi chú “Lấy top-10 từ Qdrant, rerank bằng bge-reranker-v2-m3, giữ lại 3 chunk đầu để đưa vào LLM.” · lỗi kết nối Qdrant hiển thị khối đỏ.

### A4 · Phản hồi — `/admin/feedback` (`A4-…`, `A4b-…`)
Tiêu đề + “Xuất CSV” (loading → tải `phan-hoi.csv` UTF-8 BOM). 4 thẻ số liệu: Tổng · Đúng · Sai · Sai chưa xử lý. Tab: Tất cả / Sai / Đúng / Chưa xử lý.
Hai cột: **danh sách** (badge Sai/Đúng, “✓ Đã xử lý”, thời gian, câu hỏi, lý do) và **chi tiết** (đánh giá + thời gian + `msg_id` · câu hỏi · câu trả lời của trợ lý · lý do + ghi chú của sinh viên · danh sách chunk đã dùng (link sang A3, kèm điểm rerank) · nút **Đánh dấu đã xử lý** ⇄ “Đã xử lý · bấm để mở lại” · **Thêm vào bộ test** ⇄ “Đã có trong bộ test · bấm để bỏ” · “Cập nhật tài liệu” → A2). Mỗi thao tác lưu → toast thành công/lỗi.

## 5. Bảng hành vi các nút

| Loại kết quả | Nút |
|---|---|
| Chuyển trang | Câu hỏi gợi ý, mục lịch sử, menu quản trị, tên tài liệu, chunk đã dùng, Đăng nhập (đúng), xác nhận Xóa hội thoại / Xóa tài liệu ở A3 |
| Mở hộp thoại | Xóa hội thoại, Xóa toàn bộ lịch sử, Xem PDF, Xóa / Re-index tài liệu, Đăng xuất |
| Toast | Đúng, Gửi phản hồi, Sao chép, Tạo lại, Tải PDF, Cuộc trò chuyện mới, gợi ý liên quan, Thêm tài liệu, Re-index, Xóa, Thử truy xuất, Xuất CSV, Đánh dấu đã xử lý, Thêm vào bộ test |
| Lỗi tại chỗ | Gửi câu hỏi trống, Gửi báo Sai thiếu lý do / thiếu mô tả khi chọn Khác, đăng nhập thiếu/sai, upload thiếu file/tên/sai định dạng, URL sai, Thử truy xuất trống |
| Trạng thái rỗng | Tìm lịch sử, lọc tài liệu, lọc chunk, tab phản hồi không có kết quả |

**Toast:** góc dưới phải, rộng 400px, bo 12, bóng; icon + tiêu đề 14/600 + nội dung 14px, nút đóng 32px; tự ẩn sau ~5 giây; `role="status" aria-live="polite"`. Màu: thành công `#0E5132`, lỗi `#B01C08`, thông tin `#000066`.
**Hộp thoại:** nền mờ `rgba(0,0,40,.45)`, thẻ 440px bo 16, `role="dialog" aria-modal="true"`, Esc / Hủy để đóng, bẫy focus.

## 6. Hợp đồng dữ liệu (đề xuất — chỉnh theo backend FastAPI thực tế)

```ts
type SourceType = 'pdf' | 'web';
interface Citation {             // một nguồn trong câu trả lời
  n: number;                     // số hiển thị [1], [2]...
  doc_id: string; chunk_id: string;
  title: string; type: SourceType;
  file?: string; url?: string;   // file PDF hoặc link web
  page?: number | string; loc?: string;   // "Chương 3 › Điều 14"
  excerpt_before?: string; excerpt_highlight: string; excerpt_after?: string;
  rerank_score?: number;
}
interface AnswerMessage {
  message_id: string; conversation_id: string;
  question: string;
  answer: string;                // markdown, đánh dấu trích dẫn dạng [1]
  citations: Citation[];
  status: 'ok' | 'no_source';
  created_at: string;
}
type FeedbackReason = 'wrong_info' | 'irrelevant_source' | 'missing_info' | 'outdated' | 'other';
interface FeedbackIn { message_id: string; session_id: string; vote: 'up' | 'down'; reason?: FeedbackReason; note?: string; }
interface DocumentRow {
  doc_id: string; title: string; file: string; category: string; type: 'PDF' | 'Web' | 'Ảnh';
  chunks: number; version: number; status: 'indexed' | 'processing' | 'error';
  step?: 1 | 2 | 3 | 4; error_message?: string; updated_at: string;
}
interface Chunk { chunk_id: string; doc_id: string; page: number; loc: string; tokens: number; is_table: boolean; text: string; }
```

| Endpoint | Dùng ở |
|---|---|
| `POST /api/chat` `{session_id, conversation_id?, question}` → `AnswerMessage` (khuyến nghị stream SSE) | Màn 1, 2 |
| `GET /api/conversations?session_id=` · `DELETE /api/conversations/{id}` · `DELETE /api/conversations?session_id=` | Sidebar sinh viên |
| `POST /api/feedback` `FeedbackIn` | Màn 2 |
| `GET /api/files/{doc_id}?page=` | Xem / tải PDF |
| `POST /api/admin/login` → `{access_token}` | A1 |
| `GET /api/admin/documents?q&category&status` · `POST /api/admin/documents` (multipart hoặc `{url}`) · `POST /api/admin/documents/{id}/reindex` · `DELETE /api/admin/documents/{id}` · `GET /api/admin/documents/{id}/status` | A2, A3 |
| `GET /api/admin/documents/{id}/chunks?type&q&page&cursor` · `POST /api/admin/retrieve-test` `{question, doc_id?}` | A3 |
| `GET /api/admin/feedback?tab=` · `PATCH /api/admin/feedback/{id}` `{handled?, in_test_set?}` · `GET /api/admin/feedback/export.csv` | A4 |

Mỗi point trong Qdrant lưu payload `doc_id`, `version`, `page`, `loc`, `is_table` để xóa / re-index theo tài liệu và hiển thị trích dẫn.

## 7. Trợ năng (bắt buộc)
- Dùng phần tử thật: `<button>`, `<a href>`, `<input>` + `<label for>`; nút chỉ có icon phải có `aria-label`.
- Nút bật/tắt dùng `aria-pressed`; nút mở form dùng `aria-expanded`; lỗi dùng `role="alert"`; mục đang mở `aria-current="page"`.
- Tương phản chữ ≥ 4.5:1 (không dùng `#F5250C` cho chữ nhỏ).
- Icon trang trí `aria-hidden="true"`.

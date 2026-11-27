# Trợ lý Học vụ — Bộ thiết kế giao diện

Bộ file thiết kế giao diện cho ứng dụng "Trợ lý Học vụ" (6 màn + các trạng thái).

## Có gì trong gói

| Thư mục / file | Dùng để làm gì |
|---|---|
| `SPEC.md` | **Đặc tả chính** — bố cục, từng màn, mọi trạng thái, hành vi từng nút, hợp đồng dữ liệu/API, trợ năng. |
| `screenshots/` | 19 ảnh PNG 1440px của từng màn và trạng thái — “ảnh chuẩn” để đối chiếu giao diện. |
| `prototype/` | Bản HTML **chạy được offline** (mở `prototype/index.html`). Bấm thử mọi nút, form, hộp thoại, thông báo. Font đã kèm sẵn. |
| `design-tokens/` | `tokens.css` (CSS variables) và `tokens.json` — màu Đại học Thăng Long, kiểu chữ, bo góc, khoảng cách. |
| `assets/logo-mark.svg` | Biểu tượng ứng dụng (sách mở + kính lúp). |
| `source/` | File `.dc.html` gốc của canvas (template `{{ }}` + `<sc-for>`/`<sc-if>` + class logic). Chỉ để tham khảo; cú pháp được giải thích ở đầu `prototype/dc-lite.js`. |

> Dữ liệu trong thiết kế là **minh họa**. Chỗ ghi `[…]` (mức học phí, đợt xét tốt nghiệp…) phải lấy từ backend.
> `prototype/dc-lite.js` chỉ là công cụ chạy thử — **không** dùng trong ứng dụng thật.

## Danh sách ảnh

| Ảnh | Màn / trạng thái |
|---|---|
| `01-welcome` · `01b-welcome-empty-question-error` | Màn chào · gửi câu hỏi trống |
| `02-answer-with-sources` | Câu trả lời + nguồn trích dẫn + panel nguồn |
| `02b-report-wrong-validation` | Form báo Sai, chọn “Khác” nhưng chưa mô tả |
| `02c-report-wrong-sent-toast` · `02d-marked-correct-toast` | Đã gửi báo Sai · đã đánh giá Đúng |
| `02e-pdf-viewer` · `02f-delete-conversation-dialog` | Xem PDF tại trang · xác nhận xóa hội thoại |
| `02g-new-question-no-source` · `02h-send-error` | Không tìm thấy nguồn · lỗi gửi câu hỏi |
| `A1-admin-login` · `A1b-admin-login-error` | Đăng nhập quản trị · thiếu thông tin |
| `A2-documents` · `A2b-add-document-validation` · `A2c-delete-document-dialog` | Quản lý tài liệu · form thêm báo lỗi · xác nhận xóa |
| `A3-document-detail` · `A3b-reindex-in-progress` | Chi tiết tài liệu · đang re-index |
| `A4-feedback` · `A4b-feedback-actions-toast` | Phản hồi · đã xử lý / thêm vào bộ test |

Font Be Vietnam Pro: SIL Open Font License 1.1 (`prototype/fonts/OFL-LICENSE.txt`).

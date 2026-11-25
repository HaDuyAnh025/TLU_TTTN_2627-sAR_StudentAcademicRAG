# Trợ lý Học vụ — Bộ xuất thiết kế giao diện cho AI code

Bộ file này dùng để đưa vào **Antigravity, Claude Code, Cursor** hoặc chat với **Claude** nhờ dựng giao diện thật.
Nguồn thiết kế gốc: canvas Claude Design “Giao diện RAG tra cứu học vụ” (6 màn + các trạng thái).

## Có gì trong gói

| Thư mục / file | Dùng để làm gì |
|---|---|
| `SPEC.md` | **Đặc tả chính** — bố cục, từng màn, mọi trạng thái, hành vi từng nút, hợp đồng dữ liệu/API, trợ năng. Đưa file này cho AI đầu tiên. |
| `screenshots/` | 19 ảnh PNG 1440px của từng màn và trạng thái — “ảnh chuẩn” để AI so khớp giao diện. |
| `prototype/` | Bản HTML **chạy được offline** (mở `prototype/index.html`). Bấm thử mọi nút, form, hộp thoại, thông báo. Font đã kèm sẵn. |
| `design-tokens/` | `tokens.css` (CSS variables) và `tokens.json` — màu Đại học Thăng Long, kiểu chữ, bo góc, khoảng cách. |
| `assets/logo-mark.svg` | Biểu tượng ứng dụng (sách mở + kính lúp). |
| `source/` | File `.dc.html` gốc của canvas (template `{{ }}` + `<sc-for>`/`<sc-if>` + class logic). Chỉ để tham khảo; cú pháp được giải thích ở đầu `prototype/dc-lite.js`. |

> Dữ liệu trong thiết kế là **minh họa**. Chỗ ghi `[…]` (mức học phí, đợt xét tốt nghiệp…) phải lấy từ backend.
> `prototype/dc-lite.js` chỉ là công cụ chạy thử — **không** dùng trong ứng dụng thật.

## Cách dùng

**Antigravity / Claude Code / Cursor (agent đọc được thư mục):** chép cả thư mục này vào repo, ví dụ `docs/ui-design/`, rồi dán prompt bên dưới.

**Claude.ai / ChatGPT (chat):** tải lên `SPEC.md`, `design-tokens/tokens.css` và các ảnh trong `screenshots/` của màn đang làm (làm từng màn một cho chính xác), rồi dán prompt.

## Prompt mẫu (sửa phần stack nếu cần)

```text
Bạn là frontend engineer. Hãy dựng giao diện cho ứng dụng "Trợ lý Học vụ" — chatbot RAG
tra cứu thông tin học vụ của Trường Đại học Thăng Long — đúng theo thiết kế trong docs/ui-design/.

Tài liệu:
- docs/ui-design/SPEC.md: đặc tả bắt buộc (bố cục, trạng thái, hành vi nút, API).
- docs/ui-design/screenshots/*.png: ảnh chuẩn, giao diện phải khớp về bố cục, màu, cỡ chữ, khoảng cách.
- docs/ui-design/design-tokens/tokens.css: dùng các token này, không tự đặt màu mới.
- docs/ui-design/prototype/: bản chạy thử; mở bằng trình duyệt để xem tương tác thật.
- docs/ui-design/assets/logo-mark.svg: logo.

Stack: Nuxt 3 + Vue 3 + TypeScript + Tailwind CSS (map tokens vào tailwind.config),
icon dùng lucide-vue-next, font Be Vietnam Pro (copy từ prototype/fonts).
Backend có sẵn là FastAPI; tạm dùng mock theo các interface ở mục 6 của SPEC,
gom gọi API vào một lớp services/ để sau thay bằng API thật.

Yêu cầu:
1. Tách component dùng chung: Sidebar sinh viên, Sidebar quản trị, Button (primary/secondary/danger/ghost),
   Chip, Badge, Input, SourceCard, Citation, Toast (+ store), Dialog, Composer, StatCard.
2. Trang: / (chào), /c/[id] (câu trả lời + panel nguồn), /admin/login, /admin/documents,
   /admin/documents/[id], /admin/feedback. Admin cần JWT; sinh viên không đăng nhập (session_id trong localStorage).
3. Làm đủ mọi trạng thái trong SPEC (loading, rỗng, lỗi, không tìm thấy nguồn, form lỗi tại chỗ, toast, hộp thoại)
   và bảng hành vi nút ở mục 5 — không nút nào được "im lặng".
4. Trợ năng theo mục 7 SPEC. Responsive: cột xếp chồng ở màn hẹp, bảng cuộn ngang.
5. Làm lần lượt: tokens + component dùng chung → màn 1 → màn 2 → A1 → A2 → A3 → A4.
   Sau mỗi màn, chạy ứng dụng và so với ảnh trong screenshots/, sửa chỗ lệch trước khi làm màn tiếp.
```

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

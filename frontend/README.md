# Trợ lý Học vụ — Frontend

Giao diện web cho hệ thống RAG tra cứu thông tin học vụ (sinh viên không cần đăng nhập; trang quản trị cần đăng nhập).
Next.js 16 (App Router, Cache Components) + TypeScript + Tailwind CSS v4. Giai đoạn hiện tại là **mock-first**:
toàn bộ dữ liệu lấy từ `src/services/mock.ts`, chưa gọi FastAPI.

Thiết kế chuẩn: [`../docs/ui-design/SPEC.md`](../docs/ui-design/SPEC.md), ảnh trong `../docs/ui-design/screenshots/`,
kế hoạch kiến trúc [`../docs/ui-design/PLAN.md`](../docs/ui-design/PLAN.md). Quy tắc cho agent: [`AGENTS.md`](./AGENTS.md)
(Next.js 16 khác bản cũ — đọc `node_modules/next/dist/docs/` trước khi viết code).

## Cài đặt và chạy

Yêu cầu: Node.js 20+ và npm.

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run lint     # ESLint, phải không lỗi
npm run build    # build production, phải không lỗi
npm run start    # chạy bản build
```

## Biến môi trường

Đặt trong `frontend/.env.local` (file này bị git bỏ qua). Mọi biến đều có tiền tố `NEXT_PUBLIC_` nên **lộ ra trình duyệt**, không đặt bí mật.

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | rỗng | URL gốc của FastAPI (ví dụ `http://localhost:8000`). Hiện chỉ dùng để dựng link tải file `GET /api/files/{doc_id}`. |
| `NEXT_PUBLIC_USE_MOCK` | bật (khác `"false"`) | Khi `false`, các nút "Tải PDF" / "Tải file gốc" mở link thật tới `API_BASE` thay vì hiện toast. **Chưa** chuyển các service sang API thật (xem mục "Phụ thuộc mock"). |
| `NEXT_PUBLIC_MOCK_ERROR` | không đặt | Đặt `true` để giả lập lỗi: gửi câu hỏi, tạo lại, gửi phản hồi, xử lý tài liệu (lỗi ở bước 3), thử truy xuất (lỗi Qdrant), đánh dấu phản hồi, xuất CSV. Cần khởi động lại `npm run dev` sau khi đổi. |

## Tài khoản quản trị (chỉ cho mock)

- Tên đăng nhập: `admin`
- Mật khẩu: `admin123`

Cặp này nằm cứng trong `src/services/mock.ts` và **phải xóa** khi nối backend. Token lưu ở `localStorage` khóa `sar_admin_token`.

## Dữ liệu mẫu

Trạng thái mock lưu trong `localStorage` với tiền tố `sar_mock_` (hội thoại, tin nhắn, đánh giá, tài liệu, phản hồi).
Muốn đưa về dữ liệu mẫu ban đầu: mở `/dev/components` → nút **Reset dữ liệu mẫu** (hoặc xóa các khóa `sar_mock_*` trong DevTools).
`session_id` của sinh viên lưu ở khóa `sar_session_id`.

## Các route

| Route | Màn | Ghi chú |
|---|---|---|
| `/` | Màn 1 — chào + gợi ý câu hỏi | Gửi câu hỏi → tạo hội thoại → chuyển `/c/[id]` |
| `/c/[conversationId]` | Màn 2 — chat + panel nguồn | Trả lời hiện dần, đánh giá Đúng/Sai, tạo lại, xem PDF |
| `/admin/login` | A1 — đăng nhập quản trị | |
| `/admin` | — | Chuyển sang `/admin/documents` |
| `/admin/documents` | A2 — kho tài liệu | Thêm / lọc / Re-index / Xóa, tiến trình 4 bước |
| `/admin/documents/[docId]` | A3 — chi tiết tài liệu | Chunk, thử truy xuất, Re-index, Xóa |
| `/admin/feedback` | A4 — phản hồi | Danh sách + chi tiết, xử lý, bộ test, xuất CSV |
| `/dev/components` | Trang kiểm thử thành phần | **Chỉ khi chạy dev**; bản production trả 404 |

Các route `/admin/*` (trừ `/admin/login`) nằm trong nhóm `(protected)`: `AdminAuthGuard` chuyển về `/admin/login` khi chưa có token.
Chúng đặt `export const instant = false` vì nội dung chỉ hiện sau khi đọc token ở client.

## Bố cục và màn hẹp

Từ 1024px: sidebar cạnh nội dung. Dưới 1024px: sidebar xếp trên nội dung. Màn 2 chỉ dùng 3 cột (sidebar | chat | panel nguồn) từ 1280px;
hẹp hơn thì panel nguồn nằm dưới khung chat. Bảng tài liệu cuộn ngang trong khung.

## Cấu trúc thư mục

```text
frontend/
├─ public/logo-mark.svg
└─ src/
   ├─ app/
   │  ├─ layout.tsx                 # <html lang="vi">, font Be Vietnam Pro, ToastProvider
   │  ├─ globals.css                # Tailwind v4 @theme (token từ docs/ui-design/design-tokens/tokens.css)
   │  ├─ (student)/                 # layout có SidebarStudent
   │  │  ├─ page.tsx                # /
   │  │  └─ c/[conversationId]/     # /c/[id] (page + loading)
   │  ├─ admin/
   │  │  ├─ login/page.tsx
   │  │  └─ (protected)/            # layout: AdminAuthGuard + SidebarAdmin
   │  │     ├─ documents/ (page, [docId]/page + loading)
   │  │     └─ feedback/page.tsx
   │  └─ dev/components/page.tsx    # chỉ dev
   ├─ components/
   │  ├─ ui/        # Button, Input/Textarea/Select, Badge, Chip, StatCard, Toast, Dialog, BrandLogo
   │  ├─ layout/    # SidebarStudent, SidebarAdmin
   │  ├─ student/   # WelcomeView, QuestionComposer, ConversationView, ChatThread, AnswerCard,
   │  │             # SourceCard, CitationBadge, SourcePanel, PdfViewerDialog, FeedbackWrongForm
   │  ├─ admin/     # AdminLoginForm, AdminAuthGuard, DocumentStatusToaster, DocumentsView,
   │  │             # AddDocumentForm, DocumentsTable, DocumentDetailView, ChunkListPanel,
   │  │             # RetrieveTestPanel, FeedbackManager
   │  └─ dev/       # DevComponentsView
   ├─ lib/          # types, constants, storage, date-groups, markdown, use-return-focus
   └─ services/     # api (cấu hình), chat.service, admin.service, mock (dữ liệu + xử lý giả lập)
```

## Quy ước

- Giao diện tiếng Việt; component có state/sự kiện đặt `'use client'` ở ranh giới nhỏ nhất.
- Màu, cỡ chữ, bo góc chỉ dùng token trong `globals.css` (bảng màu mặc định của Tailwind đã bị chặn).
- Mọi nút phải chuyển trang, mở hộp thoại hoặc hiện toast; lỗi form báo ngay tại ô nhập (`role="alert"`).
- Gọi dữ liệu qua `src/services/`, không import `mock.ts` trực tiếp từ component (trừ trang `/dev/components`).

## Phụ thuộc mock (chuẩn bị nối backend)

- **Service gọi thẳng mock:** `chat.service.ts` và `admin.service.ts` import `./mock`; `NEXT_PUBLIC_USE_MOCK` chưa chuyển đổi service. Cần thêm nhánh gọi HTTP (dùng `API_BASE`) trong từng hàm, giữ nguyên chữ ký.
- **Chỉ có ở mock, backend thật khác:**
  - tài khoản `admin/admin123` và lớp lỗi `MockLoginError` (`isInvalidCredentials`);
  - `createConversation` + trường `pending_question`: backend thật sẽ nhận id hội thoại từ phản hồi của `POST /api/chat`;
  - state `localStorage` `sar_mock_*`, `resetMockData()`;
  - xử lý tài liệu 4 bước bằng `setTimeout` (backend thật cần polling `GET /api/admin/documents/{id}/status` hoặc SSE).
- **Cập nhật trực tiếp bằng sự kiện `window`:** `subscribeConversations` / `subscribeAdminData` chỉ có tác dụng trong cùng trình duyệt; khi nối backend cần thay bằng refetch sau thao tác hoặc polling.
- **Tải lên chỉ gửi tên và dung lượng file:** `AddDocumentForm` chưa gửi đối tượng `File`; cần `multipart/form-data` cho `POST /api/admin/documents`.
- **Xem PDF:** `PdfViewerDialog` hiển thị đoạn trích của citation như "nội dung trang"; PLAN dự kiến endpoint trả `PdfPagePreview`.
- **Chưa có:** gửi `session_id` (service nhận nhưng bỏ qua), xử lý 401/hết hạn JWT (`AdminAuthGuard` chỉ kiểm tra có token), stream SSE thật (mock giả lập `onDelta`), `regenerate` không stream.
- **Nội dung cứng trong giao diện:** 4 nhóm / 12 câu hỏi gợi ý và 12 `doc_type` ở `lib/constants.ts`; dòng "Dữ liệu tra cứu: … thanglong.edu.vn" ở `WelcomeView`; ghi chú "top-10 … bge-reranker-v2-m3" ở `RetrieveTestPanel`; chữ "Chương 5" trong toast bộ test.

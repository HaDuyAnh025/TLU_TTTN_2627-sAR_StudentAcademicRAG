# Kế hoạch triển khai Frontend — Trợ lý Học vụ (sAR)

Tài liệu chốt kiến trúc, cấu trúc thư mục, hợp đồng dữ liệu/API và design tokens trước khi bắt đầu code giao diện trong `frontend/`.

- **Stack:** Next.js 16 App Router (`cacheComponents: true`, `partialPrefetching: true`) + TypeScript + Tailwind CSS v4 + `lucide-react` + `@radix-ui/react-dialog` + `clsx` + `next/font/google` (`Be_Vietnam_Pro` weights 400/500/600/700, subsets `vietnamese`, `latin`).
- **Tài liệu chuẩn đối chiếu:** [SPEC.md](./SPEC.md), [tokens.css](./design-tokens/tokens.css), ảnh trong [screenshots/](./screenshots/), bản chạy thử [prototype/](./prototype/).
- **Ràng buộc:** Tuân thủ [.agent/rules/frontend.md](../../.agent/rules/frontend.md) và [frontend/AGENTS.md](../../frontend/AGENTS.md).

---

## 1. Các quyết định đã chốt

1. **Phạm vi giai đoạn 1 (Mock-first):**
   - Triển khai toàn bộ **6 màn hình** cùng đầy đủ trạng thái bằng `frontend/src/services/mock.ts`.
   - **Không đụng tới `app/` (FastAPI)** trong giai đoạn này; chỉ đề xuất/nối API ở giai đoạn sau.
   - Thứ tự thực hiện: Tokens + Components dùng chung (kèm trang kiểm thử `/dev/components`) → Màn 1 (`/`) → Màn 2 (`/c/[conversationId]`) → A1 (`/admin/login`) → A2 (`/admin/documents`) → A3 (`/admin/documents/[docId]`) → A4 (`/admin/feedback`).
2. **Xem PDF tại trang (`02e-pdf-viewer.png`):**
   - Render nội dung text của trang PDF tương ứng kèm đoạn trích được tô sáng nền `#E6E5F4` (`bg-bg-highlight`), cùng nút **Tải PDF** dùng URL file (`GET /api/files/{doc_id}`).
   - Chưa dùng `iframe` hay `pdf.js`.
3. **Danh mục tài liệu (Màn A2, A3):**
   - Dùng đủ **12 `doc_type`** trong `configs/doc_meta.yaml` làm giá trị dữ liệu; ánh xạ nhãn hiển thị tiếng Việt trong `frontend/src/lib/constants.ts`:
     - `quy_che` → `Quy chế`
     - `ctdt` → `Chương trình đào tạo`
     - `quy_trinh` → `Quy trình – thủ tục`
     - `ke_hoach` → `Kế hoạch đào tạo`
     - `hoc_phi` → `Học phí`
     - `hoc_bong` → `Học bổng`
     - `mon_thay_the` → `Môn học thay thế`
     - `lien_he` → `Liên hệ`
     - `lich_thi` → `Lịch thi`
     - `tkb` → `Thời khóa biểu`
     - `thong_bao` → `Thông báo`
     - `khac` → `Khác`
   - **Không sửa `configs/doc_meta.yaml`**.
4. **Lưu state mock & Reset dữ liệu mẫu:**
   - Lưu state mock (hội thoại, tin nhắn, đánh giá/phản hồi, danh sách tài liệu & thao tác admin) vào `localStorage` với tiền tố **`sar_mock_`**.
   - Cung cấp hàm `resetMockData()` trong `src/services/mock.ts` và nút **"Reset dữ liệu mẫu"** tại `/dev/components`.
5. **Bổ sung token trong `@theme`:**
   - Thêm 2 màu từ `SPEC.md` mục 4 vào `@theme`: `--color-bg-error-soft: #FFF6F5` (nền form báo Sai) và `--color-bg-pdf-viewer: #E9ECF0` (nền khung xem PDF), ghi rõ nguồn là `SPEC mục 4`.
   - Khai báo lại `--color-white: #FFFFFF` và `--color-black: #000000` sau dòng `--color-*: initial;` để vẫn giữ được 2 màu cơ bản khi khóa bảng màu Tailwind mặc định.
6. **Kết nối Backend & Streaming SSE:**
   - Gọi FastAPI trực tiếp qua biến môi trường **`NEXT_PUBLIC_API_BASE`** (đã cấu hình trong `frontend/.env.local`) kết hợp CORS phía FastAPI.
   - `POST /api/chat` sử dụng **SSE**: thiết kế `chat` service có callback `onDelta(text)` để ở giai đoạn mock giả lập hiệu ứng chữ hiện dần trước khi chốt `AnswerMessage` hoàn chỉnh.
7. **Bổ sung hợp đồng dữ liệu & endpoint còn thiếu vào `services/` + `mock.ts`:**
   - Bổ sung `GET /api/conversations/{id}`, `GET /api/admin/documents/{id}`, luồng `regenerate` câu trả lời, `stats` tài liệu (A2), `unhandled_wrong_count` (badge sidebar & A4), `related_questions` và `title` hội thoại.

---

## 2. Cấu trúc thư mục `frontend/src/` (Next.js 16 + Cache Components)

Nguyên tắc áp dụng với `cacheComponents: true` & `partialPrefetching: true`:
- Layout/Page mặc định là Server Component (static shell).
- Các route động (`/c/[conversationId]`, `/admin/documents/[docId]`) đọc `params: Promise<...>` hoặc `useSearchParams()` **phải bọc trong `<Suspense>`** và có `loading.tsx`.
- Component có state, sự kiện, `localStorage` (`session_id`, `sar_mock_*`, JWT admin) đặt `'use client'` ở ranh giới nhỏ nhất cần thiết.
- Logo đặt tại `frontend/public/logo-mark.svg` (đã có sẵn).

```text
frontend/src/
├─ app/
│  ├─ globals.css                         # @import "tailwindcss"; + @theme inline + @theme + :focus-visible
│  ├─ layout.tsx                          # RootLayout (<html lang="vi">, Be_Vietnam_Pro, ToastProvider)
│  ├─ (student)/                          # Route group sinh viên (dùng chung SidebarStudent)
│  │  ├─ layout.tsx                       # Shell: [SidebarStudent 260px] + khung chat co giãn
│  │  ├─ page.tsx                         # Màn 1 (/): Màn hình chào + gợi ý câu hỏi
│  │  └─ c/
│  │     └─ [conversationId]/
│  │        ├─ loading.tsx                # Fallback Suspense cho dynamic route
│  │        └─ page.tsx                   # Màn 2 (/c/:conversationId): Chat + Panel nguồn (bọc <Suspense>)
│  ├─ admin/
│  │  ├─ login/
│  │  │  └─ page.tsx                      # Màn A1 (/admin/login): Đăng nhập quản trị (không sidebar)
│  │  └─ (protected)/                     # Route group A2–A4 (SidebarAdmin + AdminAuthGuard)
│  │     ├─ layout.tsx                    # Shell: [SidebarAdmin 240px] + vùng nội dung padding 32px
│  │     ├─ documents/
│  │     │  ├─ page.tsx                   # Màn A2 (/admin/documents): Kho tài liệu + thêm/lọc/xóa/re-index
│  │     │  └─ [docId]/
│  │     │     ├─ loading.tsx             # Fallback Suspense cho dynamic [docId]
│  │     │     └─ page.tsx                # Màn A3 (/admin/documents/:docId): Chi tiết + chunk + thử truy xuất
│  │     └─ feedback/
│  │        └─ page.tsx                   # Màn A4 (/admin/feedback): Danh sách + chi tiết phản hồi + xuất CSV
│  └─ dev/
│     └─ components/
│        └─ page.tsx                      # Trang kiểm thử primitive UI + nút "Reset dữ liệu mẫu"
│
├─ components/
│  ├─ ui/
│  │  ├─ Button.tsx                       # primary / secondary / danger / ghost, min-h 44px / sm 40px, loading
│  │  ├─ Input.tsx                        # Input, Textarea, Select + label + thông báo lỗi tại chỗ (role="alert")
│  │  ├─ Badge.tsx                        # Trạng thái (Đã index / Đang xử lý / Lỗi / PDF / Web / Ảnh / Đúng / Sai)
│  │  ├─ Chip.tsx                         # Chip gợi ý liên quan, lý do báo Sai, tab lọc (aria-pressed)
│  │  ├─ Dialog.tsx                       # Bọc @radix-ui/react-dialog (xác nhận xóa/re-index/đăng xuất, xem PDF)
│  │  ├─ Toast.tsx                        # ToastProvider + ToastViewport (góc dưới phải, 400px, ~5s, role="status")
│  │  ├─ StatCard.tsx                     # Thẻ số liệu (A2, A4)
│  │  └─ BrandLogo.tsx                    # /logo-mark.svg + lockup "Trợ lý Học vụ"
│  ├─ layout/
│  │  ├─ SidebarStudent.tsx               # 'use client': + Cuộc trò chuyện mới, tìm kiếm, nhóm ngày, xóa toàn bộ
│  │  └─ SidebarAdmin.tsx                 # 'use client': Tài liệu, Phản hồi (badge đỏ), Mở trang SV, Đăng xuất
│  ├─ student/
│  │  ├─ WelcomeView.tsx                  # 'use client': Tiêu đề, ô hỏi lớn, 4 thẻ danh mục gợi ý
│  │  ├─ QuestionComposer.tsx             # 'use client': Ô nhập + nút gửi + validate trống tại chỗ
│  │  ├─ ChatThread.tsx                   # 'use client': Bong bóng user, AnswerCard, loading/streaming/lỗi/no_source
│  │  ├─ AnswerCard.tsx                   # 'use client': Nội dung + trích dẫn [n], SourceCard grid, Đúng/Sai/Sao chép/Tạo lại
│  │  ├─ CitationBadge.tsx                # Ô số 24×24 bo 6px (chọn/đổi nguồn đang xem)
│  │  ├─ SourceCard.tsx                   # Thẻ nguồn trích dẫn (aria-pressed)
│  │  ├─ FeedbackWrongForm.tsx            # 'use client': 5 chip lý do + textarea bắt buộc khi chọn "Khác"
│  │  ├─ SourcePanel.tsx                  # 'use client': Panel phải 340px (Vị trí/Trang, đoạn trích tô #E6E5F4, nút PDF/Web)
│  │  └─ PdfViewerDialog.tsx              # 'use client': Modal 760px render text trang PDF + tô sáng + Tải PDF
│  └─ admin/
│     ├─ AdminAuthGuard.tsx               # 'use client': Kiểm tra JWT trong localStorage, redirect /admin/login
│     ├─ AddDocumentForm.tsx              # 'use client': Tab Tải file / Link web, 12 doc_type, dải 4 bước, validate tại chỗ
│     ├─ DocumentsTable.tsx               # 'use client': Bộ lọc + bảng cuộn ngang + polling tiến trình 4 bước
│     ├─ DocumentDetailView.tsx           # 'use client': 6 ô metadata + nút Tải file gốc / Re-index / Xóa
│     ├─ ChunkListPanel.tsx               # 'use client': Lọc Tất cả/Văn bản/Bảng, tìm nội dung, lọc trang, xem thêm
│     ├─ RetrieveTestPanel.tsx            # 'use client': Thử truy xuất + thanh điểm rerank + xử lý lỗi Qdrant
│     └─ FeedbackManager.tsx              # 'use client': 4 stat cards, tabs, danh sách + chi tiết + Xuất CSV
│
├─ lib/
│  ├─ types.ts                            # TypeScript interfaces mục 6 SPEC + các trường bổ sung
│  ├─ storage.ts                          # Helper localStorage an toàn SSR: session_id, JWT admin, sar_mock_*
│  ├─ date-groups.ts                      # Nhóm lịch sử: Hôm nay / 7 ngày trước / Tháng trước + format ngày giờ
│  ├─ markdown.tsx                        # Render câu trả lời có danh sách đánh số + chèn CitationBadge [1] tương tác
│  └─ constants.ts                        # 4 nhóm gợi ý màn 1, map 12 doc_type → nhãn tiếng Việt, 5 lý do báo Sai
│
└─ services/
   ├─ api.ts                              # HTTP client dùng NEXT_PUBLIC_API_BASE + Bearer token + switch mock/real
   ├─ mock.ts                             # Mock đầy đủ 6 màn, lưu localStorage sar_mock_*, export resetMockData()
   ├─ chat.service.ts                     # chatStream(onDelta), conversations CRUD, regenerate, feedback, fileUrl
   └─ admin.service.ts                    # login, documents CRUD/detail/reindex/status, chunks, retrieveTest, feedback
```

---

## 3. Bảng đối chiếu & Hợp đồng API (Mục 6 SPEC + phần bổ sung)

> **Lưu ý hiện trạng:** Thư mục `app/` hiện đang **trống (0 file)**. Toàn bộ các endpoint dưới đây sẽ được mock trước trong `src/services/mock.ts` và thống nhất interface trong `src/services/` để nối FastAPI ở giai đoạn sau.

### 3.1. Bảng endpoint

| Nhóm | Method & Path | Payload / Query | Response chính | Dùng ở | Trạng thái trong `app/` | Nguồn định nghĩa |
|---|---|---|---|---|---|---|
| Chat (SSE) | `POST /api/chat` | `{ session_id, conversation_id?, question }` | SSE events (`delta`, `done` → `AnswerMessage` kèm `title`, `related_questions`) | Màn 1, 2 | Chưa có | SPEC mục 6 + Quyết định 6 & bổ sung |
| Tạo lại | `POST /api/messages/{id}/regenerate` | `{ session_id }` | SSE events → `AnswerMessage` mới | Màn 2 | Chưa có | Bổ sung từ SPEC mục 4 |
| Danh sách hội thoại | `GET /api/conversations?session_id=` | `session_id` | `ConversationSummary[]` (`conversation_id`, `title`, `updated_at`) | Sidebar SV | Chưa có | SPEC mục 6 |
| Chi tiết hội thoại | `GET /api/conversations/{id}?session_id=` | `id`, `session_id` | `ConversationDetail` (`conversation_id`, `title`, `messages: AnswerMessage[]`) | Màn 2 | Chưa có | Bổ sung |
| Xóa 1 hội thoại | `DELETE /api/conversations/{id}` | `id` | `{ ok: true }` | Màn 2 | Chưa có | SPEC mục 6 |
| Xóa toàn bộ lịch sử | `DELETE /api/conversations?session_id=` | `session_id` | `{ ok: true }` | Sidebar SV | Chưa có | SPEC mục 6 |
| Gửi / đổi đánh giá | `POST /api/feedback` | `FeedbackIn` | `{ feedback_id, status }` | Màn 2 | Chưa có | SPEC mục 6 |
| Tải / xem PDF | `GET /api/files/{doc_id}?page=` | `doc_id`, `page?` | File stream (hoặc text trang + highlight ở endpoint/metadata) | Màn 2, A3 | Chưa có | SPEC mục 6 |
| Đăng nhập Admin | `POST /api/admin/login` | `{ username, password }` | `{ access_token, token_type }` | A1 | Chưa có | SPEC mục 6 |
| Danh sách & stats tài liệu | `GET /api/admin/documents?q&category&status` | `q?`, `category?`, `status?` | `{ items: DocumentRow[], stats: DocumentStats }` | A2 | Chưa có | SPEC mục 6 + bổ sung `stats` |
| Thêm tài liệu | `POST /api/admin/documents` | `multipart/form-data` (file, title, category, effective_date?, replace_existing) hoặc `{ url, title, category, effective_date?, replace_existing }` | `DocumentRow` | A2 | Chưa có | SPEC mục 6 + SPEC mục 4 |
| Chi tiết tài liệu | `GET /api/admin/documents/{id}` | `id` | `DocumentDetail` (`doc_id`, `title`, `file`, `category`, `type`, `version`, `replaces_version?`, `pages`, `chunks`, `indexed_at`, `status`, `step?`) | A3 | Chưa có | Bổ sung |
| Re-index | `POST /api/admin/documents/{id}/reindex` | `id` | `{ doc_id, status: 'processing', step: 1 }` | A2, A3 | Chưa có | SPEC mục 6 |
| Xóa tài liệu | `DELETE /api/admin/documents/{id}` | `id` | `{ ok: true, deleted_chunks }` | A2, A3 | Chưa có | SPEC mục 6 |
| Trạng thái index | `GET /api/admin/documents/{id}/status` | `id` | `{ doc_id, status, step?, error_message?, chunks? }` | A2, A3 | Chưa có | SPEC mục 6 |
| Danh sách chunk | `GET /api/admin/documents/{id}/chunks?type&q&page&cursor` | `type?`, `q?`, `page?`, `cursor?` | `{ items: Chunk[], total, next_cursor? }` | A3 | Chưa có | SPEC mục 6 |
| Thử truy xuất | `POST /api/admin/retrieve-test` | `{ question, doc_id? }` | `{ items: RetrieveTestHit[] }` | A3 | Chưa có | SPEC mục 6 |
| Danh sách phản hồi | `GET /api/admin/feedback?tab=` | `tab`: `all \| down \| up \| unhandled` | `{ items: AdminFeedbackItem[], stats: FeedbackStats, unhandled_wrong_count: number }` | A4, Sidebar Admin | Chưa có | SPEC mục 6 + bổ sung |
| Cập nhật phản hồi | `PATCH /api/admin/feedback/{id}` | `{ handled?, in_test_set? }` | `AdminFeedbackItem` | A4 | Chưa có | SPEC mục 6 |
| Xuất CSV phản hồi | `GET /api/admin/feedback/export.csv` | — | File `phan-hoi.csv` (UTF-8 BOM) | A4 | Chưa có | SPEC mục 6 |

### 3.2. Kiểu dữ liệu bổ sung vào `src/lib/types.ts` (mở rộng mục 6 SPEC)

- `DocCategory`: 12 giá trị `quy_che | ctdt | quy_trinh | ke_hoach | hoc_phi | hoc_bong | mon_thay_the | lien_he | lich_thi | tkb | thong_bao | khac`.
- `AnswerMessage`: giữ nguyên các trường mục 6 SPEC (`message_id`, `conversation_id`, `question`, `answer`, `citations`, `status`, `created_at`) và bổ sung `title?: string`, `related_questions?: string[]`, `feedback?: { vote: 'up' | 'down'; reason?: FeedbackReason; note?: string }`.
- `DocumentStats`: `{ indexed_count: number; total_chunks: number; processing_count: number; error_count: number }`.
- `FeedbackStats` & `unhandled_wrong_count`: `{ total: number; up_count: number; down_count: number; unhandled_wrong_count: number }`.
- `PdfPagePreview` (phục vụ modal `02e`): `{ doc_id: string; title: string; file: string; page: number; text_before: string; highlight: string; text_after: string; download_url: string }`.

---

## 4. Mẫu `frontend/src/app/globals.css` (Tailwind v4 `@theme`)

```css
@import "tailwindcss";

@theme inline {
  --font-sans: var(--font-be-vietnam-pro), system-ui, sans-serif;
}

@theme {
  /* Chặn bảng màu Tailwind mặc định (blue-500, gray-500...) theo .agent/rules/frontend.md */
  --color-*: initial;
  --color-transparent: transparent;
  --color-current: currentColor;
  --color-white: #FFFFFF;
  --color-black: #000000;

  /* Brand (tokens.css) */
  --color-brand-navy: #000066;
  --color-brand-navy-soft: #0000661A;
  --color-brand-red: #F5250C;

  /* Text (tokens.css) */
  --color-text-primary: #111827;
  --color-text-secondary: #374151;
  --color-text-tertiary: #4B5563;
  --color-text-muted: #5B6472;
  --color-text-label: #5B5A96;
  --color-text-on-brand: #FFFFFF;

  /* Surfaces (tokens.css + bổ sung từ SPEC mục 4) */
  --color-bg-page: #F5F6F8;
  --color-bg-surface: #FFFFFF;
  --color-bg-subtle: #EEF1F5;
  --color-bg-hover: #F1F3F6;
  --color-bg-highlight: #E6E5F4;
  --color-bg-error-soft: #FFF6F5;    /* Nguồn: SPEC mục 4 (nền form báo Sai) */
  --color-bg-pdf-viewer: #E9ECF0;   /* Nguồn: SPEC mục 4 (nền vùng xem PDF) */

  /* Borders (tokens.css) */
  --color-border-default: #E3E6EB;
  --color-border-strong: #D5D9E0;
  --color-border-input: #C9CED6;
  --color-border-divider: #EEF0F3;

  /* Status (tokens.css) */
  --color-error: #C81E0A;
  --color-error-text: #B01C08;
  --color-error-bg: #FEEDEB;
  --color-error-border: #F7C4BC;
  --color-success: #166534;
  --color-success-bg: #E7F5EE;
  --color-success-strong: #0E5132;
  --color-info-bg: #E8E8F5;
  --color-scrim: rgba(0, 0, 40, 0.45);

  /* Typography (tách từ shorthand tokens.css sang chuẩn Tailwind v4) */
  --text-display: 32px;
  --text-display--line-height: 1.25;
  --text-display--font-weight: 700;

  --text-h1: 26px;
  --text-h1--line-height: 1.3;
  --text-h1--font-weight: 700;

  --text-h2: 18px;
  --text-h2--line-height: 1.35;
  --text-h2--font-weight: 700;

  --text-h3: 16px;
  --text-h3--line-height: 1.4;
  --text-h3--font-weight: 600;

  --text-body-lg: 16px;
  --text-body-lg--line-height: 1.6;
  --text-body-lg--font-weight: 400;

  --text-body: 15px;
  --text-body--line-height: 1.6;
  --text-body--font-weight: 400;

  --text-body-sm: 14px;
  --text-body-sm--line-height: 1.55;
  --text-body-sm--font-weight: 400;

  --text-label: 14px;
  --text-label--line-height: 1.4;
  --text-label--font-weight: 600;

  --text-caption: 13px;
  --text-caption--line-height: 1.5;
  --text-caption--font-weight: 400;

  --text-caption-sm: 12px;
  --text-caption-sm--line-height: 1.5;
  --text-caption-sm--font-weight: 400;

  --text-overline: 12px;
  --text-overline--line-height: 1.4;
  --text-overline--font-weight: 600;
  --text-overline--letter-spacing: 0.04em;

  --text-stat: 28px;
  --text-stat--line-height: 1.2;
  --text-stat--font-weight: 700;

  /* Radius (tokens.css + ô hỏi SPEC mục 4) */
  --radius-xs: 6px;
  --radius-sm: 8px;
  --radius-md: 10px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-ask: 18px;               /* Nguồn: SPEC mục 4 (ô hỏi lớn màn 1) */
  --radius-full: 999px;

  /* Sizes & Layout widths (tokens.css) */
  --spacing-control: 44px;
  --spacing-control-sm: 40px;
  --spacing-sidebar-student: 260px;
  --spacing-sidebar-admin: 240px;
  --spacing-source-panel: 340px;
  --container-chat: 760px;
  --container-welcome: 960px;

  /* Effects (tokens.css) */
  --shadow-toast: 0 10px 30px rgba(0, 0, 40, 0.25);
  --shadow-dialog: 0 16px 40px rgba(0, 0, 40, 0.22);
}

@layer base {
  body {
    background-color: var(--color-bg-page);
    color: var(--color-text-primary);
    font-family: var(--font-sans);
  }

  :where(button, a, input, textarea, select):focus-visible {
    outline: 2px solid var(--color-brand-navy);
    outline-offset: 2px;
  }
}
```

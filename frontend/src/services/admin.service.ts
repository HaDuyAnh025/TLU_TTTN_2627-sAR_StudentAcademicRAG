/**
 * Dịch vụ quản trị. Giai đoạn mock-first: gọi thẳng services/mock.ts.
 * Khi nối FastAPI chỉ cần thay thân hàm, giữ nguyên chữ ký.
 */
import { clearAdminToken, getAdminToken, setAdminToken } from "@/lib/storage";
import type {
  AddDocumentInput,
  AdminFeedbackItem,
  AdminFeedbackList,
  AdminLoginRequest,
  ChunkListQuery,
  ChunkListResponse,
  DocumentDetail,
  DocumentListQuery,
  DocumentListResponse,
  DocumentRow,
  DocumentStatusResponse,
  FeedbackTab,
  RetrieveTestHit,
} from "@/lib/types";
import {
  ADMIN_CHANGED_EVENT,
  MockLoginError,
  mockAddDocument,
  mockAdminLogin,
  mockDeleteDocument,
  mockDocumentStatus,
  mockExportFeedbackCsv,
  mockGetDocument,
  mockListChunks,
  mockListDocuments,
  mockListFeedback,
  mockReindexDocument,
  mockRetrieveTest,
  mockUpdateFeedback,
} from "./mock";

const TOKEN_CHANGED_EVENT = "sar:admin-token-changed";

/** Sai tên đăng nhập hoặc mật khẩu (khác với lỗi kết nối). */
export function isInvalidCredentials(error: unknown): boolean {
  return error instanceof MockLoginError;
}

// --- Phiên đăng nhập -------------------------------------------------------

/** POST /api/admin/login — lưu JWT vào localStorage (sar_admin_token). */
export async function login(req: AdminLoginRequest): Promise<void> {
  const res = await mockAdminLogin(req);
  setAdminToken(res.access_token);
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

export function logout(): void {
  clearAdminToken();
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

export { getAdminToken };

/** Dùng với useSyncExternalStore để theo dõi token. */
export function subscribeAdminToken(callback: () => void): () => void {
  window.addEventListener(TOKEN_CHANGED_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(TOKEN_CHANGED_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

/** Nhận thông báo khi dữ liệu admin (tài liệu, phản hồi) thay đổi. */
export function subscribeAdminData(callback: () => void): () => void {
  window.addEventListener(ADMIN_CHANGED_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(ADMIN_CHANGED_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

// --- Tài liệu --------------------------------------------------------------

/** GET /api/admin/documents?q&category&status */
export function listDocuments(query: DocumentListQuery = {}): Promise<DocumentListResponse> {
  return mockListDocuments(query);
}

/** GET /api/admin/documents/{id} — null nếu không tồn tại. */
export function getDocument(id: string): Promise<DocumentDetail | null> {
  return mockGetDocument(id);
}

/** POST /api/admin/documents — trả về dòng tài liệu ở trạng thái đang xử lý. */
export function addDocument(input: AddDocumentInput): Promise<DocumentRow> {
  return mockAddDocument(input);
}

/** POST /api/admin/documents/{id}/reindex */
export function reindexDocument(id: string) {
  return mockReindexDocument(id);
}

/** DELETE /api/admin/documents/{id} */
export function deleteDocument(id: string) {
  return mockDeleteDocument(id);
}

/** GET /api/admin/documents/{id}/status */
export function getDocumentStatus(id: string): Promise<DocumentStatusResponse> {
  return mockDocumentStatus(id);
}

/** GET /api/admin/documents/{id}/chunks */
export function listChunks(id: string, query: ChunkListQuery = {}): Promise<ChunkListResponse> {
  return mockListChunks(id, query);
}

/** POST /api/admin/retrieve-test */
export function retrieveTest(req: {
  question: string;
  doc_id?: string;
}): Promise<{ items: RetrieveTestHit[] }> {
  return mockRetrieveTest(req);
}

// --- Phản hồi --------------------------------------------------------------

/** GET /api/admin/feedback?tab= */
export function listFeedback(tab: FeedbackTab = "all"): Promise<AdminFeedbackList> {
  return mockListFeedback(tab);
}

/** PATCH /api/admin/feedback/{id} */
export function updateFeedback(
  id: string,
  patch: { handled?: boolean; in_test_set?: boolean },
): Promise<AdminFeedbackItem> {
  return mockUpdateFeedback(id, patch);
}

/** GET /api/admin/feedback/export.csv — nội dung CSV UTF-8 có BOM. */
export function exportFeedbackCsv(): Promise<string> {
  return mockExportFeedbackCsv();
}

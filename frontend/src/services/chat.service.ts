/**
 * Dịch vụ chat cho màn sinh viên. Giai đoạn mock-first: gọi thẳng services/mock.ts.
 * Khi nối FastAPI chỉ cần thay thân hàm, giữ nguyên chữ ký.
 */
import type {
  AnswerMessage,
  ConversationDetail,
  ConversationSummary,
  FeedbackIn,
  FeedbackOut,
} from "@/lib/types";
import { API_BASE } from "./api";
import {
  CONVERSATIONS_CHANGED_EVENT,
  mockChatStream,
  mockCreateConversation,
  mockDeleteAllConversations,
  mockDeleteConversation,
  mockGetConversation,
  mockListConversations,
  mockRegenerate,
  mockSendFeedback,
} from "./mock";

export interface ChatRequest {
  session_id: string;
  conversation_id?: string;
  question: string;
}

export interface ChatStreamOptions {
  /** Nhận từng đoạn chữ của câu trả lời (giả lập chữ hiện dần). */
  onDelta?: (text: string) => void;
  signal?: AbortSignal;
}

/** POST /api/chat (SSE). Trả về AnswerMessage hoàn chỉnh khi stream kết thúc; ném lỗi nếu mất kết nối. */
export function chatStream(
  req: ChatRequest,
  options: ChatStreamOptions = {},
): Promise<AnswerMessage> {
  return mockChatStream(
    { conversation_id: req.conversation_id, question: req.question },
    options,
  );
}

/** GET /api/conversations?session_id= */
export function listConversations(sessionId: string): Promise<ConversationSummary[]> {
  void sessionId; // mock chưa dùng; API thật gửi kèm session_id
  return mockListConversations();
}

/** GET /api/conversations/{id}?session_id= — null nếu không tồn tại. */
export function getConversation(
  id: string,
  sessionId: string,
): Promise<ConversationDetail | null> {
  void sessionId;
  return mockGetConversation(id);
}

/**
 * Chỉ mock: tạo hội thoại ngay từ màn 1 để chuyển sang /c/[id]; màn 2 sẽ gửi
 * `pending_question` qua chatStream. Khi nối backend thật, màn 1 sẽ gọi chatStream
 * không kèm conversation_id và nhận id từ phản hồi.
 */
export function createConversation(
  question: string,
  sessionId: string,
): Promise<ConversationSummary> {
  void sessionId;
  return mockCreateConversation(question);
}

/** DELETE /api/conversations/{id} */
export function deleteConversation(id: string): Promise<void> {
  return mockDeleteConversation(id);
}

/** DELETE /api/conversations?session_id= */
export function deleteAllConversations(sessionId: string): Promise<void> {
  void sessionId;
  return mockDeleteAllConversations();
}

/** POST /api/feedback — gửi hoặc đổi đánh giá Đúng/Sai. */
export function sendFeedback(input: FeedbackIn): Promise<FeedbackOut> {
  return mockSendFeedback(input);
}

/** POST /api/messages/{id}/regenerate — trả về AnswerMessage mới thay thế câu cũ. */
export function regenerate(
  messageId: string,
  sessionId: string,
  options: { signal?: AbortSignal } = {},
): Promise<AnswerMessage> {
  void sessionId;
  return mockRegenerate(messageId, options);
}

/** GET /api/files/{doc_id}?page= — URL tải/xem file gốc. */
export function fileUrl(docId: string, page?: number | string): string {
  const query = page !== undefined ? `?page=${encodeURIComponent(String(page))}` : "";
  return `${API_BASE}/api/files/${encodeURIComponent(docId)}${query}`;
}

/** Đăng ký nhận thông báo khi danh sách hội thoại thay đổi (cùng tab hoặc tab khác). */
export function subscribeConversations(callback: () => void): () => void {
  window.addEventListener(CONVERSATIONS_CHANGED_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(CONVERSATIONS_CHANGED_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

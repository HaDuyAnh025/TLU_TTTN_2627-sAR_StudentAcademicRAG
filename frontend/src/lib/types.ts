export type SourceType = "pdf" | "web";

export interface Citation {
  n: number;
  doc_id: string;
  chunk_id: string;
  title: string;
  type: SourceType;
  file?: string;
  url?: string;
  page?: number | string;
  loc?: string;
  excerpt_before?: string;
  excerpt_highlight: string;
  excerpt_after?: string;
  rerank_score?: number;
}

export type FeedbackReason =
  | "wrong_info"
  | "irrelevant_source"
  | "missing_info"
  | "outdated"
  | "other";

export interface MessageFeedback {
  vote: "up" | "down";
  reason?: FeedbackReason;
  note?: string;
}

export interface AnswerMessage {
  message_id: string;
  conversation_id: string;
  question: string;
  answer: string;
  citations: Citation[];
  status: "ok" | "no_source";
  created_at: string;
  title?: string;
  related_questions?: string[];
  feedback?: MessageFeedback;
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  updated_at: string;
}

export interface ConversationDetail {
  conversation_id: string;
  title: string;
  messages: AnswerMessage[];
  /** Chỉ mock: câu hỏi đầu tiên vừa tạo từ màn 1, màn 2 sẽ gửi đi khi mở. */
  pending_question?: string;
}

export interface FeedbackIn {
  message_id: string;
  session_id: string;
  vote: "up" | "down";
  reason?: FeedbackReason;
  note?: string;
}

export interface FeedbackOut {
  feedback_id: string;
  status: string;
}

export type DocCategory =
  | "quy_che"
  | "ctdt"
  | "quy_trinh"
  | "ke_hoach"
  | "hoc_phi"
  | "hoc_bong"
  | "mon_thay_the"
  | "lien_he"
  | "lich_thi"
  | "tkb"
  | "thong_bao"
  | "khac";

export type DocumentSourceType = "PDF" | "Web" | "Ảnh";
export type DocumentStatus = "indexed" | "processing" | "error";
export type IndexStep = 1 | 2 | 3 | 4;

export interface DocumentRow {
  doc_id: string;
  title: string;
  file: string;
  category: DocCategory;
  type: DocumentSourceType;
  chunks: number;
  version: number;
  status: DocumentStatus;
  step?: IndexStep;
  error_message?: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentRow {
  replaces_version?: number;
  pages: number;
  indexed_at: string;
  effective_date?: string;
  url?: string;
}

export interface DocumentStats {
  indexed_count: number;
  total_chunks: number;
  processing_count: number;
  error_count: number;
}

export interface DocumentStatusResponse {
  doc_id: string;
  status: DocumentStatus;
  step?: IndexStep;
  error_message?: string;
  chunks?: number;
}

export interface Chunk {
  chunk_id: string;
  doc_id: string;
  page: number;
  loc: string;
  tokens: number;
  is_table: boolean;
  text: string;
}

export interface RetrieveTestHit {
  rank: number;
  chunk_id: string;
  doc_id: string;
  doc_title?: string;
  page: number;
  loc?: string;
  excerpt: string;
  rerank_score: number;
}

export type FeedbackTab = "all" | "down" | "up" | "unhandled";

export interface FeedbackChunkRef {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  page: number | string;
  rerank_score: number;
}

export interface AdminFeedbackItem {
  feedback_id: string;
  message_id: string;
  vote: "up" | "down";
  reason?: FeedbackReason;
  note?: string;
  question: string;
  answer: string;
  created_at: string;
  handled: boolean;
  in_test_set: boolean;
  chunks: FeedbackChunkRef[];
}

export interface FeedbackStats {
  total: number;
  up_count: number;
  down_count: number;
  unhandled_wrong_count: number;
}

export interface PdfPagePreview {
  doc_id: string;
  title: string;
  file: string;
  page: number;
  text_before: string;
  highlight: string;
  text_after: string;
  download_url: string;
}

export interface AdminLoginRequest {
  username: string;
  password: string;
}

export interface AdminLoginResponse {
  access_token: string;
  token_type: string;
}

export interface DocumentListQuery {
  q?: string;
  category?: DocCategory | "";
  status?: DocumentStatus | "";
}

export interface DocumentListResponse {
  items: DocumentRow[];
  /** Số liệu tính trên toàn bộ tài liệu, không phụ thuộc bộ lọc. */
  stats: DocumentStats;
  /** Tổng số tài liệu (không lọc), dùng cho "Hiển thị x / tổng". */
  total: number;
}

export interface AddDocumentInput {
  source: "file" | "url";
  file_name?: string;
  file_size?: number;
  url?: string;
  title: string;
  category: DocCategory;
  effective_date?: string;
  replace_existing: boolean;
}

export type ChunkTypeFilter = "all" | "text" | "table";

export interface ChunkListQuery {
  type?: ChunkTypeFilter;
  q?: string;
  /** Lọc theo số trang. */
  page?: number;
  /** Vị trí bắt đầu của trang kết quả tiếp theo. */
  cursor?: string;
}

export interface ChunkListResponse {
  items: Chunk[];
  total: number;
  next_cursor?: string;
}

export interface AdminFeedbackList {
  items: AdminFeedbackItem[];
  stats: FeedbackStats;
  unhandled_wrong_count: number;
}

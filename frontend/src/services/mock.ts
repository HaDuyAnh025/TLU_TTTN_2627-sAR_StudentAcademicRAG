/**
 * Dữ liệu giả cho giai đoạn mock-first. NỘI DUNG CHỈ MINH HỌA, không phải quy định thật của trường.
 * State lưu trong localStorage với tiền tố `sar_mock_` (xem lib/storage.ts).
 */
import { SUGGESTED_QUESTION_GROUPS } from "@/lib/constants";
import { clearAllMockStorage, getMockStorage, setMockStorage } from "@/lib/storage";
import type {
  AddDocumentInput,
  AdminFeedbackItem,
  AdminFeedbackList,
  AdminLoginRequest,
  AdminLoginResponse,
  AnswerMessage,
  Chunk,
  ChunkListQuery,
  ChunkListResponse,
  Citation,
  ConversationDetail,
  ConversationSummary,
  DocCategory,
  DocumentDetail,
  DocumentListQuery,
  DocumentListResponse,
  DocumentRow,
  DocumentStatusResponse,
  FeedbackIn,
  FeedbackOut,
  FeedbackTab,
  IndexStep,
  RetrieveTestHit,
  SourceType,
} from "@/lib/types";

export const MOCK_DELAY_MS = 1500;
export const CONVERSATIONS_CHANGED_EVENT = "sar:conversations-changed";
export const ADMIN_CHANGED_EVENT = "sar:admin-changed";

const CONVERSATIONS_KEY = "conversations";
const ADMIN_DOCS_KEY = "admin_documents";
const ADMIN_FEEDBACK_KEY = "admin_feedback";
const FEEDBACK_DELAY_MS = 600;
const STREAM_TICK_MS = 30;
const WORDS_PER_TICK = 2;

export const MOCK_NO_SOURCE_ANSWER =
  "Mình chưa tìm thấy thông tin này trong các văn bản hiện có của trường nên không thể trả lời chắc chắn. " +
  "Bạn có thể hỏi lại theo cách khác, hoặc liên hệ Phòng Đào tạo để được hướng dẫn trực tiếp.";

export const MOCK_CONNECTION_ERROR =
  "Không gửi được câu hỏi do mất kết nối tới máy chủ.";

// ---------------------------------------------------------------------------
// Kho tri thức giả
// ---------------------------------------------------------------------------

interface SourceSeed {
  title: string;
  type: SourceType;
  file?: string;
  url?: string;
  loc?: string;
  page?: number | string;
  before?: string;
  highlight: string;
  after?: string;
}

interface Topic {
  id: string;
  keywords: string[];
  answer: string;
  sources: SourceSeed[];
  related?: string[];
}

const QUY_CHE: SourceSeed = {
  title: "Quy chế đào tạo trình độ đại học",
  type: "pdf",
  file: "quy-che-dao-tao-dai-hoc.pdf",
  loc: "Chương 3 › Điều 14",
  page: 18,
  before:
    "Điều 14. Xét và công nhận tốt nghiệp. 1. Sinh viên được xét và công nhận tốt nghiệp khi có đủ các điều kiện sau: ",
  highlight:
    "a) Tích lũy đủ học phần, số tín chỉ và hoàn thành các nội dung bắt buộc khác theo yêu cầu của chương trình đào tạo; b) Điểm trung bình tích lũy toàn khóa đạt từ trung bình trở lên; c) Tại thời điểm xét tốt nghiệp không bị truy cứu trách nhiệm hình sự hoặc không đang trong thời gian bị kỷ luật ở mức đình chỉ học tập.",
};

const TOPICS: Topic[] = [
  {
    id: "rut_hoc_phan",
    keywords: ["rut bot hoc phan", "rut hoc phan"],
    answer:
      "Sinh viên có thể rút bớt học phần đã đăng ký trong thời hạn rút học phần của học kỳ:\n\n1. Nộp đơn hoặc thực hiện trên hệ thống đăng ký trong thời hạn được thông báo. [1]\n2. Sau khi rút, tổng số tín chỉ của học kỳ vẫn phải đạt mức tối thiểu theo quy định. [1]\n\nHọc phí của học phần đã rút được xử lý theo thông báo học phí của học kỳ. [2]",
    sources: [
      {
        title: "Quy chế đào tạo trình độ đại học",
        type: "pdf",
        file: "quy-che-dao-tao-dai-hoc.pdf",
        loc: "Chương 2 › Điều 9",
        page: 11,
        highlight:
          "Sinh viên được rút bớt học phần đã đăng ký trong thời hạn quy định của học kỳ, với điều kiện khối lượng học tập còn lại không thấp hơn mức tối thiểu.",
      },
      {
        title: "Thông báo đăng ký học phần học kỳ",
        type: "web",
        url: "https://thanglong.edu.vn/thong-bao/dang-ky-hoc-phan",
        highlight: "Thời hạn rút bớt học phần được công bố trong lịch đăng ký của từng học kỳ.",
      },
    ],
  },
  {
    id: "tot_nghiep",
    keywords: ["tot nghiep"],
    answer:
      "Theo quy chế đào tạo hiện hành, sinh viên được xét và công nhận tốt nghiệp khi đáp ứng đủ các điều kiện sau:\n\n1. Tích lũy đủ số học phần, số tín chỉ và hoàn thành các nội dung bắt buộc của chương trình đào tạo. [1]\n2. Điểm trung bình tích lũy toàn khóa đạt từ mức trung bình trở lên. [1]\n3. Đạt chuẩn đầu ra ngoại ngữ và tin học theo quy định của trường. [2]\n4. Tại thời điểm xét, không bị truy cứu trách nhiệm hình sự và không trong thời gian bị kỷ luật đình chỉ học tập. [1]\n\nThời gian nộp hồ sơ của từng đợt xét tốt nghiệp được nhà trường thông báo riêng trên website. [3]",
    sources: [
      QUY_CHE,
      {
        title: "Quy định chuẩn đầu ra ngoại ngữ, tin học",
        type: "pdf",
        file: "quy-dinh-chuan-dau-ra.pdf",
        loc: "Mục 2",
        page: 3,
        highlight:
          "Sinh viên phải đạt chuẩn đầu ra ngoại ngữ và tin học theo quy định của trường trước khi được xét công nhận tốt nghiệp.",
      },
      {
        title: "Thông báo xét tốt nghiệp đợt [ĐỢT]",
        type: "web",
        url: "https://thanglong.edu.vn/thong-bao/xet-tot-nghiep",
        highlight:
          "Thời gian nộp hồ sơ và danh sách dự kiến xét tốt nghiệp của từng đợt được đăng tại trang thông báo của trường.",
      },
    ],
    related: [
      "Hồ sơ xét tốt nghiệp gồm những gì?",
      "Chuẩn đầu ra tiếng Anh của ngành KHMT là gì?",
      "Thiếu tín chỉ thì có được xét ở đợt sau không?",
    ],
  },
  {
    id: "diem_tb",
    keywords: ["diem trung binh"],
    answer:
      "Điểm trung bình tích lũy là trung bình có trọng số theo số tín chỉ của các học phần đã học, không tính học phần điều kiện:\n\n1. Mỗi học phần có điểm chữ được quy đổi sang thang điểm 4. [1]\n2. Lấy tổng (điểm quy đổi × số tín chỉ) chia cho tổng số tín chỉ đã tích lũy. [1]\n\nHọc phần học lại hoặc học cải thiện được tính theo lần có điểm cao nhất. [1]",
    sources: [
      {
        title: "Quy chế đào tạo trình độ đại học",
        type: "pdf",
        file: "quy-che-dao-tao-dai-hoc.pdf",
        loc: "Chương 3 › Điều 12",
        page: 15,
        highlight:
          "Điểm trung bình tích lũy được tính theo công thức trung bình có trọng số của điểm học phần với số tín chỉ tương ứng.",
      },
    ],
  },
  {
    id: "canh_bao",
    keywords: ["canh bao hoc tap", "canh bao"],
    answer:
      "Sinh viên bị cảnh báo học tập khi kết quả học tập của học kỳ hoặc của cả quá trình thấp hơn ngưỡng quy định:\n\n1. Điểm trung bình học kỳ hoặc điểm trung bình tích lũy thấp hơn ngưỡng cảnh báo của trường. [1]\n2. Số tín chỉ không đạt trong học kỳ vượt quá tỷ lệ cho phép. [1]\n\nKết quả cảnh báo được thông báo đến sinh viên sau khi có điểm của học kỳ. [1]",
    sources: [
      {
        title: "Quy chế đào tạo trình độ đại học",
        type: "pdf",
        file: "quy-che-dao-tao-dai-hoc.pdf",
        loc: "Chương 3 › Điều 16",
        page: 21,
        highlight:
          "Cảnh báo học tập được thực hiện sau mỗi học kỳ đối với sinh viên có kết quả học tập thấp hơn ngưỡng quy định.",
      },
    ],
  },
  {
    id: "toi_da",
    keywords: ["toi da"],
    answer:
      "Số tín chỉ đăng ký mỗi học kỳ nằm trong khoảng tối thiểu và tối đa theo quy định:\n\n1. Mức tối đa phụ thuộc vào học lực của sinh viên ở học kỳ liền trước. [1]\n2. Sinh viên bị cảnh báo học tập chỉ được đăng ký ở mức thấp hơn. [1]\n\nVí dụ cụ thể theo từng ngành được nêu trong kế hoạch đào tạo. [2]",
    sources: [
      {
        title: "Quy chế đào tạo trình độ đại học",
        type: "pdf",
        file: "quy-che-dao-tao-dai-hoc.pdf",
        loc: "Chương 2 › Điều 8",
        page: 9,
        highlight:
          "Khối lượng học tập tối thiểu và tối đa sinh viên được đăng ký trong mỗi học kỳ chính được quy định theo học lực của học kỳ trước.",
      },
      {
        title: "Kế hoạch đào tạo toàn khóa",
        type: "pdf",
        file: "ke-hoach-dao-tao.pdf",
        loc: "Mục 1",
        page: 2,
        highlight: "Kế hoạch nêu số tín chỉ dự kiến của từng học kỳ theo ngành đào tạo.",
      },
    ],
  },
  {
    id: "hoc_bong",
    keywords: ["hoc bong"],
    answer:
      "Học bổng khuyến khích học tập được xét theo từng học kỳ dựa trên kết quả học tập và rèn luyện:\n\n1. Đạt kết quả học tập và điểm rèn luyện từ mức quy định trở lên trong học kỳ xét. [1]\n2. Không bị kỷ luật và không có học phần không đạt trong học kỳ xét. [1]\n\nSố suất và thời gian nhận hồ sơ được công bố qua thông báo của trường. [2]",
    sources: [
      {
        title: "Quy định học bổng khuyến khích học tập",
        type: "pdf",
        file: "quy-dinh-hoc-bong.pdf",
        loc: "Điều 4",
        page: 4,
        highlight:
          "Sinh viên được xét học bổng khuyến khích học tập khi đạt kết quả học tập và rèn luyện từ mức quy định trở lên.",
      },
      {
        title: "Thông báo xét học bổng học kỳ",
        type: "web",
        url: "https://thanglong.edu.vn/thong-bao/hoc-bong",
        highlight: "Thời gian nhận hồ sơ xét học bổng được thông báo theo từng học kỳ.",
      },
    ],
  },
  {
    id: "hoc_phi",
    keywords: ["hoc phi"],
    answer:
      "Học phí được tính theo số tín chỉ sinh viên đăng ký và áp dụng theo thông báo học phí của từng năm học. [1]\n\nSinh viên cần nộp học phí trước hạn ghi trong thông báo của học kỳ; nộp muộn có thể bị hạn chế đăng ký học phần hoặc xét học bổng. [2]",
    sources: [
      {
        title: "Thông báo mức học phí năm học",
        type: "pdf",
        file: "thong-bao-hoc-phi.pdf",
        loc: "Mục 1",
        page: 1,
        highlight:
          "Học phí được thu theo số tín chỉ đăng ký của từng học kỳ, mức thu áp dụng theo thông báo của năm học.",
      },
      {
        title: "Thông báo nộp học phí học kỳ",
        type: "web",
        url: "https://thanglong.edu.vn/thong-bao/hoc-phi",
        highlight: "Hạn nộp học phí được ghi rõ trong thông báo của từng học kỳ.",
      },
    ],
  },
  {
    id: "dang_ky",
    keywords: ["dang ky hoc phan"],
    answer:
      "Thời gian đăng ký học phần được công bố theo lịch của từng học kỳ:\n\n1. Đợt đăng ký chính diễn ra trước khi học kỳ bắt đầu. [1]\n2. Đợt đăng ký bổ sung hoặc điều chỉnh diễn ra trong tuần đầu của học kỳ. [1]\n\nSinh viên theo dõi lịch cụ thể trên website của trường. [2]",
    sources: [
      {
        title: "Quy chế đào tạo trình độ đại học",
        type: "pdf",
        file: "quy-che-dao-tao-dai-hoc.pdf",
        loc: "Chương 2 › Điều 7",
        page: 8,
        highlight:
          "Sinh viên đăng ký học phần theo kế hoạch và thời hạn do nhà trường công bố trước mỗi học kỳ.",
      },
      {
        title: "Lịch đăng ký học phần học kỳ tới",
        type: "web",
        url: "https://thanglong.edu.vn/thong-bao/lich-dang-ky",
        highlight: "Lịch đăng ký học phần của học kỳ tới được đăng trên trang thông báo đào tạo.",
      },
    ],
  },
  {
    id: "bao_luu",
    keywords: ["bao luu"],
    answer:
      "Để xin bảo lưu kết quả học tập, sinh viên thực hiện các bước sau:\n\n1. Chuẩn bị đơn xin bảo lưu nêu rõ lý do và thời gian dự kiến. [1]\n2. Nộp đơn tại Phòng Đào tạo trong thời hạn quy định. [1]\n3. Chờ quyết định của nhà trường; kết quả đã tích lũy được bảo lưu theo quyết định. [1]",
    sources: [
      {
        title: "Quy trình thủ tục bảo lưu kết quả học tập",
        type: "pdf",
        file: "quy-trinh-bao-luu.pdf",
        loc: "Mục 3",
        page: 2,
        highlight:
          "Sinh viên nộp đơn xin bảo lưu kết quả học tập tại Phòng Đào tạo; nhà trường xem xét và ra quyết định.",
      },
    ],
  },
  {
    id: "xac_nhan",
    keywords: ["giay xac nhan", "xac nhan sinh vien"],
    answer:
      "Sinh viên xin giấy xác nhận sinh viên theo các bước:\n\n1. Điền phiếu đề nghị cấp giấy xác nhận (nêu rõ mục đích sử dụng). [1]\n2. Nộp phiếu tại bộ phận một cửa hoặc Phòng Đào tạo. [1]\n3. Nhận giấy theo lịch hẹn ghi trên phiếu. [1]",
    sources: [
      {
        title: "Quy trình cấp giấy xác nhận sinh viên",
        type: "pdf",
        file: "quy-trinh-xac-nhan-sinh-vien.pdf",
        loc: "Mục 1",
        page: 1,
        highlight:
          "Sinh viên điền phiếu đề nghị và nộp tại bộ phận một cửa; giấy xác nhận được trả theo lịch hẹn.",
      },
    ],
  },
  {
    id: "chuyen_nganh",
    keywords: ["chuyen nganh"],
    answer:
      "Hồ sơ xin chuyển ngành thường gồm:\n\n1. Đơn xin chuyển ngành nêu rõ nguyện vọng và lý do. [1]\n2. Bảng điểm các học kỳ đã học. [1]\n3. Các giấy tờ khác theo thông báo của khoa tiếp nhận. [1]\n\nSinh viên cần đáp ứng điều kiện về kết quả học tập để được xét chuyển. [1]",
    sources: [
      {
        title: "Quy định chuyển ngành đào tạo",
        type: "pdf",
        file: "quy-dinh-chuyen-nganh.pdf",
        loc: "Điều 3",
        page: 3,
        highlight:
          "Sinh viên nộp đơn và bảng điểm đến khoa tiếp nhận; việc chuyển ngành được xét theo điều kiện về kết quả học tập.",
      },
    ],
  },
];

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "d")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function findTopic(question: string): Topic | null {
  const padded = ` ${normalize(question)} `;
  for (const topic of TOPICS) {
    if (topic.keywords.some((kw) => padded.includes(` ${kw} `))) return topic;
  }
  return null;
}

function slugify(text: string): string {
  return normalize(text).replace(/\s+/g, "-");
}

function buildCitations(topic: Topic): Citation[] {
  return topic.sources.map((seed, index) => {
    const docId = `doc_${slugify(seed.title)}`;
    return {
      n: index + 1,
      doc_id: docId,
      chunk_id: `${docId}_p${seed.page ?? 0}_c1`,
      title: seed.title,
      type: seed.type,
      file: seed.file,
      url: seed.url,
      page: seed.page,
      loc: seed.loc,
      excerpt_before: seed.before,
      excerpt_highlight: seed.highlight,
      excerpt_after: seed.after,
      rerank_score: Number((0.92 - index * 0.11).toFixed(2)),
    };
  });
}

function relatedFor(topic: Topic, question: string): string[] {
  if (topic.related) return topic.related;
  const asked = normalize(question);
  return SUGGESTED_QUESTION_GROUPS.flatMap((g) => [...g.questions])
    .filter((q) => normalize(q) !== asked)
    .slice(0, 3);
}

function newId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function makeTitle(question: string): string {
  const clean = question.trim().replace(/[?？]+$/, "").replace(/\s+/g, " ");
  return clean.length > 48 ? `${clean.slice(0, 47)}…` : clean;
}

export function buildMockAnswer(
  question: string,
  conversationId: string,
  createdAt: string = new Date().toISOString(),
): AnswerMessage {
  const topic = findTopic(question);
  const base = {
    message_id: newId("msg"),
    conversation_id: conversationId,
    question,
    created_at: createdAt,
    title: makeTitle(question),
  };
  if (!topic) {
    return { ...base, answer: MOCK_NO_SOURCE_ANSWER, citations: [], status: "no_source" };
  }
  return {
    ...base,
    answer: topic.answer,
    citations: buildCitations(topic),
    status: "ok",
    related_questions: relatedFor(topic, question),
  };
}

// ---------------------------------------------------------------------------
// Lưu trữ hội thoại (localStorage: sar_mock_conversations)
// ---------------------------------------------------------------------------

interface StoredConversation extends ConversationDetail {
  updated_at: string;
}

function ago(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function seedConversations(): StoredConversation[] {
  const day = 24 * 60;
  const seeds: Array<{ title: string; question: string; minutesAgo: number }> = [
    { title: "Điều kiện xét tốt nghiệp", question: "Điều kiện để được xét tốt nghiệp là gì?", minutesAgo: 1 },
    { title: "Học phí học kỳ 2", question: "Học phí học kỳ 2 năm nay được tính thế nào?", minutesAgo: 3 },
    { title: "Thủ tục bảo lưu kết quả học tập", question: "Thủ tục xin bảo lưu kết quả học tập?", minutesAgo: 2 * day },
    { title: "Đăng ký học phần bổ sung", question: "Thời gian đăng ký học phần bổ sung?", minutesAgo: 3 * day },
    { title: "Học bổng khuyến khích học tập", question: "Điều kiện nhận học bổng khuyến khích học tập?", minutesAgo: 5 * day },
    { title: "Quy định chuyển ngành", question: "Hồ sơ chuyển ngành gồm những gì?", minutesAgo: 15 * day },
    { title: "Cách tính điểm trung bình tích lũy", question: "Điểm trung bình tích lũy được tính thế nào?", minutesAgo: 22 * day },
  ];
  return seeds.map((seed, i) => {
    const id = `conv_seed_${i + 1}`;
    const at = ago(seed.minutesAgo);
    const message = buildMockAnswer(seed.question, id, at);
    return {
      conversation_id: id,
      title: seed.title,
      updated_at: at,
      messages: [{ ...message, title: seed.title }],
    };
  });
}

function readAll(): StoredConversation[] {
  const stored = getMockStorage<StoredConversation[] | null>(CONVERSATIONS_KEY, null);
  if (stored) return stored;
  const seeded = seedConversations();
  setMockStorage(CONVERSATIONS_KEY, seeded);
  return seeded;
}

function writeAll(list: StoredConversation[]): void {
  setMockStorage(CONVERSATIONS_KEY, list);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CONVERSATIONS_CHANGED_EVENT));
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

// ---------------------------------------------------------------------------
// API giả
// ---------------------------------------------------------------------------

export async function mockListConversations(): Promise<ConversationSummary[]> {
  return readAll()
    .map(({ conversation_id, title, updated_at }) => ({ conversation_id, title, updated_at }))
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}

export async function mockGetConversation(id: string): Promise<ConversationDetail | null> {
  const found = readAll().find((c) => c.conversation_id === id);
  if (!found) return null;
  const { conversation_id, title, messages, pending_question } = found;
  return { conversation_id, title, messages, pending_question };
}

/** Tạo hội thoại rỗng kèm câu hỏi chờ gửi (màn 1 → màn 2). */
export async function mockCreateConversation(question: string): Promise<ConversationSummary> {
  const conversation: StoredConversation = {
    conversation_id: newId("conv"),
    title: makeTitle(question),
    updated_at: new Date().toISOString(),
    messages: [],
    pending_question: question,
  };
  writeAll([conversation, ...readAll()]);
  return {
    conversation_id: conversation.conversation_id,
    title: conversation.title,
    updated_at: conversation.updated_at,
  };
}

export async function mockDeleteConversation(id: string): Promise<void> {
  writeAll(readAll().filter((c) => c.conversation_id !== id));
}

export async function mockDeleteAllConversations(): Promise<void> {
  writeAll([]);
}

export interface MockChatRequest {
  conversation_id?: string;
  question: string;
}

export interface MockChatOptions {
  onDelta?: (text: string) => void;
  signal?: AbortSignal;
}

export async function mockChatStream(
  req: MockChatRequest,
  options: MockChatOptions = {},
): Promise<AnswerMessage> {
  const { onDelta, signal } = options;
  await sleep(MOCK_DELAY_MS, signal);

  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error(MOCK_CONNECTION_ERROR);
  }

  const all = readAll();
  const existing = all.find((c) => c.conversation_id === req.conversation_id);
  const conversationId = existing?.conversation_id ?? newId("conv");
  const message = buildMockAnswer(req.question, conversationId);

  if (onDelta) {
    const tokens = message.answer.split(/(\s+)/).filter((t) => t.length > 0);
    // Mỗi "từ" gồm cả khoảng trắng đi kèm; gửi WORDS_PER_TICK từ mỗi nhịp.
    let buffer = "";
    let words = 0;
    for (const token of tokens) {
      buffer += token;
      if (token.trim().length > 0) words += 1;
      if (words >= WORDS_PER_TICK) {
        onDelta(buffer);
        buffer = "";
        words = 0;
        await sleep(STREAM_TICK_MS, signal);
      }
    }
    if (buffer) onDelta(buffer);
  }

  const now = message.created_at;
  const rest = all.filter((c) => c.conversation_id !== conversationId);
  const updated: StoredConversation = existing
    ? {
        ...existing,
        messages: [...existing.messages, message],
        updated_at: now,
        pending_question: undefined,
      }
    : {
        conversation_id: conversationId,
        title: message.title ?? makeTitle(req.question),
        updated_at: now,
        messages: [message],
      };
  writeAll([updated, ...rest]);
  return message;
}

export interface MockRegenerateOptions {
  signal?: AbortSignal;
}

/** Tạo lại câu trả lời: thay thế tin nhắn cũ (đánh giá cũ bị xóa) bằng AnswerMessage mới. */
export async function mockRegenerate(
  messageId: string,
  options: MockRegenerateOptions = {},
): Promise<AnswerMessage> {
  await sleep(MOCK_DELAY_MS, options.signal);
  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error(MOCK_CONNECTION_ERROR);
  }
  const all = readAll();
  const conversation = all.find((c) => c.messages.some((m) => m.message_id === messageId));
  const old = conversation?.messages.find((m) => m.message_id === messageId);
  if (!conversation || !old) throw new Error("Không tìm thấy câu trả lời cần tạo lại.");

  const fresh = buildMockAnswer(old.question, conversation.conversation_id);
  const messages = conversation.messages.map((m) => (m.message_id === messageId ? fresh : m));
  writeAll(
    all.map((c) =>
      c.conversation_id === conversation.conversation_id
        ? { ...c, messages, updated_at: fresh.created_at }
        : c,
    ),
  );
  return fresh;
}

/** Lưu/đổi đánh giá cho một câu trả lời (mỗi message_id một đánh giá), đồng thời đưa vào hàng đợi admin. */
export async function mockSendFeedback(input: FeedbackIn): Promise<FeedbackOut> {
  await sleep(FEEDBACK_DELAY_MS);
  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error(MOCK_CONNECTION_ERROR);
  }
  const conversations = readAll();
  const message = conversations
    .flatMap((c) => c.messages)
    .find((m) => m.message_id === input.message_id);

  const list = readAdminFeedback();
  const existing = list.find((f) => f.message_id === input.message_id);
  const record: AdminFeedbackItem = {
    feedback_id: existing?.feedback_id ?? newId("fb"),
    message_id: input.message_id,
    vote: input.vote,
    reason: input.reason,
    note: input.note,
    question: message?.question ?? existing?.question ?? "",
    answer: message?.answer ?? existing?.answer ?? "",
    created_at: new Date().toISOString(),
    handled: false,
    in_test_set: existing?.in_test_set ?? false,
    chunks: (message?.citations ?? []).map((c) => ({
      chunk_id: c.chunk_id,
      doc_id: c.doc_id,
      doc_title: c.title,
      page: c.page ?? "—",
      rerank_score: c.rerank_score ?? 0,
    })),
  };
  writeAdminFeedback([record, ...list.filter((f) => f.message_id !== input.message_id)]);

  writeAll(
    conversations.map((c) => ({
      ...c,
      messages: c.messages.map((m) =>
        m.message_id === input.message_id
          ? { ...m, feedback: { vote: input.vote, reason: input.reason, note: input.note } }
          : m,
      ),
    })),
  );
  return { feedback_id: record.feedback_id, status: "received" };
}

/** Xóa toàn bộ state mock (sar_mock_*); lần truy cập sau dữ liệu mẫu được tạo lại. */
export function resetMockData(): void {
  cancelAdminTimers();
  clearAllMockStorage();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CONVERSATIONS_CHANGED_EVENT));
    window.dispatchEvent(new Event(ADMIN_CHANGED_EVENT));
  }
}

// ===========================================================================
// ADMIN (giai đoạn 3a) — dữ liệu và xử lý tài liệu giả lập
// ===========================================================================

/**
 * CHỈ DÙNG CHO MOCK: tài khoản quản trị giả lập, mật khẩu nằm ngay trong mã nguồn phía trình duyệt.
 * Khi nối FastAPI, xóa hằng số này; đăng nhập thật do backend kiểm tra và trả JWT.
 */
export const MOCK_ADMIN_USERNAME = "admin";
export const MOCK_ADMIN_PASSWORD = "admin123";

const LOGIN_DELAY_MS = 800;
const UPLOAD_DELAY_MS = 1000;
const ADMIN_STEP_MS = 1000;
const ADMIN_FAST_DELAY_MS = 400;

export class MockLoginError extends Error {
  constructor() {
    super("Tên đăng nhập hoặc mật khẩu không đúng.");
    this.name = "MockLoginError";
  }
}

export async function mockAdminLogin(req: AdminLoginRequest): Promise<AdminLoginResponse> {
  await sleep(LOGIN_DELAY_MS);
  if (req.username.trim() !== MOCK_ADMIN_USERNAME || req.password !== MOCK_ADMIN_PASSWORD) {
    throw new MockLoginError();
  }
  return { access_token: `mock.${newId("jwt")}`, token_type: "bearer" };
}

// --- Tài liệu -------------------------------------------------------------

interface StoredDocument extends DocumentDetail {
  /** Chỉ mock: tài liệu cũ bị gỡ khi bản mới xử lý xong. */
  replaces_doc_id?: string;
}

function emitAdminChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(ADMIN_CHANGED_EVENT));
  }
}

function docId(title: string): string {
  return `doc_${slugify(title)}`;
}

function seedDocuments(): StoredDocument[] {
  const day = 24 * 60;
  const base = (
    title: string,
    file: string,
    category: DocCategory,
    type: DocumentDetail["type"],
    chunks: number,
    pages: number,
    minutesAgo: number,
  ): StoredDocument => ({
    doc_id: docId(title),
    title,
    file,
    category,
    type,
    chunks,
    version: 1,
    status: "indexed",
    updated_at: ago(minutesAgo),
    pages,
    indexed_at: ago(minutesAgo),
    url: type === "Web" ? `https://${file}` : undefined,
  });
  return [
    base("Quy chế đào tạo trình độ đại học", "quy-che-dao-tao-dai-hoc.pdf", "quy_che", "PDF", 142, 34, 8 * day),
    base("Quy định chuẩn đầu ra ngoại ngữ, tin học", "chuan-dau-ra-ngoai-ngu-tin-hoc.pdf", "quy_che", "PDF", 38, 6, 8 * day),
    base("Biểu học phí năm học [NĂM HỌC]", "bieu-hoc-phi.pdf", "hoc_phi", "PDF", 64, 5, 7 * day),
    base("Quy định xét học bổng khuyến khích học tập", "hoc-bong-khuyen-khich.pdf", "hoc_bong", "PDF", 45, 9, 7 * day),
    base("Hướng dẫn đăng ký học phần", "thanglong.edu.vn/huong-dan-dang-ky-hoc-phan", "quy_trinh", "Web", 21, 4, 6 * day),
    base("Thông báo xét tốt nghiệp đợt [ĐỢT]", "thanglong.edu.vn/thong-bao/xet-tot-nghiep", "thong_bao", "Web", 6, 2, 2),
    {
      ...base("Mẫu đơn xin bảo lưu kết quả học tập", "don-bao-luu-scan.jpg", "quy_trinh", "Ảnh", 0, 1, 5 * day),
      status: "error",
      error_message: "OCR không đọc được: ảnh mờ, hãy tải lại bản rõ hơn",
    },
  ];
}

function readDocs(): StoredDocument[] {
  const stored = getMockStorage<StoredDocument[] | null>(ADMIN_DOCS_KEY, null);
  if (stored) return stored;
  const seeded = seedDocuments();
  setMockStorage(ADMIN_DOCS_KEY, seeded);
  return seeded;
}

function writeDocs(list: StoredDocument[]): void {
  setMockStorage(ADMIN_DOCS_KEY, list);
  emitAdminChanged();
}

function toRow(doc: StoredDocument): DocumentRow {
  return {
    doc_id: doc.doc_id,
    title: doc.title,
    file: doc.file,
    category: doc.category,
    type: doc.type,
    chunks: doc.chunks,
    version: doc.version,
    status: doc.status,
    step: doc.step,
    error_message: doc.error_message,
    updated_at: doc.updated_at,
  };
}

// --- Xử lý 4 bước giả lập -------------------------------------------------

const adminTimers = new Map<string, ReturnType<typeof setTimeout>>();

function cancelAdminTimers(): void {
  adminTimers.forEach((timer) => clearTimeout(timer));
  adminTimers.clear();
}

function hash(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h;
}

function scheduleStep(id: string): void {
  if (adminTimers.has(id)) return;
  adminTimers.set(
    id,
    setTimeout(() => advanceDocument(id), ADMIN_STEP_MS),
  );
}

function advanceDocument(id: string): void {
  adminTimers.delete(id);
  const docs = readDocs();
  const doc = docs.find((d) => d.doc_id === id);
  if (!doc || doc.status !== "processing") return;

  const step = doc.step ?? 1;
  const now = new Date().toISOString();

  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true" && step === 3) {
    writeDocs(
      docs.map((d) =>
        d.doc_id === id
          ? {
              ...d,
              status: "error",
              step: undefined,
              chunks: 0,
              updated_at: now,
              error_message: "Không tạo được embedding: mất kết nối tới dịch vụ mô hình.",
            }
          : d,
      ),
    );
    return;
  }

  if (step < 4) {
    writeDocs(docs.map((d) => (d.doc_id === id ? { ...d, step: (step + 1) as IndexStep } : d)));
    scheduleStep(id);
    return;
  }

  const chunks = doc.chunks > 0 ? doc.chunks : 8 + (hash(doc.title) % 53);
  writeDocs(
    docs
      .filter((d) => d.doc_id !== doc.replaces_doc_id)
      .map((d) =>
        d.doc_id === id
          ? {
              ...d,
              status: "indexed",
              step: undefined,
              error_message: undefined,
              replaces_doc_id: undefined,
              chunks,
              pages: d.pages || 1 + (hash(d.title) % 12),
              indexed_at: now,
              updated_at: now,
            }
          : d,
      ),
  );
}

/** Sau khi tải lại trang, các tài liệu đang xử lý mất bộ đếm giờ → khởi động lại từ bước hiện tại. */
function resumeProcessing(docs: StoredDocument[]): void {
  for (const doc of docs) {
    if (doc.status === "processing") scheduleStep(doc.doc_id);
  }
}

function computeStats(docs: StoredDocument[]) {
  return {
    indexed_count: docs.filter((d) => d.status === "indexed").length,
    total_chunks: docs.reduce((sum, d) => sum + d.chunks, 0),
    processing_count: docs.filter((d) => d.status === "processing").length,
    error_count: docs.filter((d) => d.status === "error").length,
  };
}

export async function mockListDocuments(query: DocumentListQuery = {}): Promise<DocumentListResponse> {
  const docs = readDocs();
  resumeProcessing(docs);
  const q = normalize(query.q?.trim() ?? "");
  const items = docs
    .filter((d) => !query.category || d.category === query.category)
    .filter((d) => !query.status || d.status === query.status)
    .filter((d) => !q || normalize(`${d.title} ${d.file}`).includes(q))
    .map(toRow);
  return { items, stats: computeStats(docs), total: docs.length };
}

export async function mockGetDocument(id: string): Promise<DocumentDetail | null> {
  const doc = readDocs().find((d) => d.doc_id === id);
  if (!doc) return null;
  resumeProcessing([doc]);
  const { replaces_doc_id, ...detail } = doc;
  void replaces_doc_id;
  return detail;
}

export async function mockAddDocument(input: AddDocumentInput): Promise<DocumentRow> {
  await sleep(UPLOAD_DELAY_MS);
  const docs = readDocs();
  const file =
    input.source === "url"
      ? (input.url ?? "").replace(/^https?:\/\//i, "")
      : (input.file_name ?? "tai-lieu.pdf");
  const ext = file.split(".").pop()?.toLowerCase();
  const type: DocumentDetail["type"] =
    input.source === "url" ? "Web" : ext === "pdf" ? "PDF" : "Ảnh";

  const replaced = input.replace_existing
    ? docs.find((d) => normalize(d.title) === normalize(input.title))
    : undefined;
  let id = docId(input.title);
  if (docs.some((d) => d.doc_id === id)) id = `${id}_v${(replaced?.version ?? 1) + 1}`;

  const now = new Date().toISOString();
  const doc: StoredDocument = {
    doc_id: id,
    title: input.title.trim(),
    file,
    category: input.category,
    type,
    chunks: 0,
    version: replaced ? replaced.version + 1 : 1,
    replaces_version: replaced?.version,
    replaces_doc_id: replaced?.doc_id,
    status: "processing",
    step: 1,
    updated_at: now,
    pages: 0,
    indexed_at: now,
    effective_date: input.effective_date || undefined,
    url: input.source === "url" ? input.url : undefined,
  };
  writeDocs([doc, ...docs]);
  scheduleStep(id);
  return toRow(doc);
}

export async function mockReindexDocument(
  id: string,
): Promise<{ doc_id: string; status: "processing"; step: 1 }> {
  await sleep(ADMIN_FAST_DELAY_MS);
  const docs = readDocs();
  if (!docs.some((d) => d.doc_id === id)) throw new Error("Không tìm thấy tài liệu.");
  writeDocs(
    docs.map((d) =>
      d.doc_id === id
        ? {
            ...d,
            status: "processing",
            step: 1,
            error_message: undefined,
            updated_at: new Date().toISOString(),
          }
        : d,
    ),
  );
  scheduleStep(id);
  return { doc_id: id, status: "processing", step: 1 };
}

export async function mockDeleteDocument(id: string): Promise<{ ok: true; deleted_chunks: number }> {
  await sleep(ADMIN_FAST_DELAY_MS);
  const docs = readDocs();
  const doc = docs.find((d) => d.doc_id === id);
  if (!doc) throw new Error("Không tìm thấy tài liệu.");
  const timer = adminTimers.get(id);
  if (timer) clearTimeout(timer);
  adminTimers.delete(id);
  writeDocs(docs.filter((d) => d.doc_id !== id));
  return { ok: true, deleted_chunks: doc.chunks };
}

export async function mockDocumentStatus(id: string): Promise<DocumentStatusResponse> {
  const docs = readDocs();
  resumeProcessing(docs);
  const doc = docs.find((d) => d.doc_id === id);
  if (!doc) throw new Error("Không tìm thấy tài liệu.");
  return {
    doc_id: doc.doc_id,
    status: doc.status,
    step: doc.step,
    error_message: doc.error_message,
    chunks: doc.chunks,
  };
}

// --- Chunk & thử truy xuất ------------------------------------------------

const QUY_CHE_DOC = docId("Quy chế đào tạo trình độ đại học");
const CHUAN_DAU_RA_DOC = docId("Quy định chuẩn đầu ra ngoại ngữ, tin học");

type ChunkSeed = Pick<Chunk, "page" | "loc" | "text"> & { is_table?: boolean };

/** Chunk viết tay (nội dung minh họa). Các chunk còn lại của tài liệu được sinh tự động cho đủ `doc.chunks`. */
const SAMPLE_CHUNKS: Record<string, ChunkSeed[]> = {
  [QUY_CHE_DOC]: [
    { page: 1, loc: "Chương 1 › Điều 1", text: "Điều 1. Phạm vi điều chỉnh và đối tượng áp dụng\nQuy chế này quy định về tổ chức đào tạo trình độ đại học, bao gồm tổ chức giảng dạy, đánh giá kết quả học tập và công nhận tốt nghiệp." },
    { page: 2, loc: "Chương 1 › Điều 2", text: "Điều 2. Giải thích từ ngữ\nHọc phần là khối lượng kiến thức tương đối trọn vẹn; tín chỉ là đơn vị đo khối lượng học tập; chương trình đào tạo là văn bản xác định mục tiêu, nội dung và kế hoạch học tập." },
    { page: 3, loc: "Chương 1 › Điều 3", text: "Điều 3. Chương trình đào tạo và thời gian học tập\nThời gian thiết kế của chương trình đào tạo được nêu trong chương trình; sinh viên có thể rút ngắn hoặc kéo dài thời gian học trong giới hạn cho phép." },
    { page: 5, loc: "Chương 1 › Điều 5", text: "Điều 5. Tổ chức lớp học phần\nLớp học phần được tổ chức theo đăng ký của sinh viên và kế hoạch giảng dạy của khoa; lớp có thể bị hủy nếu số sinh viên đăng ký thấp hơn mức tối thiểu." },
    { page: 7, loc: "Chương 2 › Điều 6", text: "Điều 6. Đăng ký nhập học\nSinh viên trúng tuyển hoàn thành thủ tục nhập học theo thông báo; trường hợp chưa kịp nhập học có thể xin bảo lưu kết quả tuyển sinh theo quy định." },
    { page: 8, loc: "Chương 2 › Điều 7", text: "Điều 7. Đăng ký học phần\nSinh viên đăng ký học phần theo kế hoạch và thời hạn do nhà trường công bố trước mỗi học kỳ." },
    { page: 9, loc: "Chương 2 › Điều 8", text: "Điều 8. Khối lượng học tập\nKhối lượng học tập tối thiểu và tối đa sinh viên được đăng ký trong mỗi học kỳ chính được quy định theo học lực của học kỳ trước." },
    { page: 11, loc: "Chương 2 › Điều 9", text: "Điều 9. Rút bớt học phần đã đăng ký\nSinh viên được rút bớt học phần trong thời hạn quy định, với điều kiện khối lượng học tập còn lại không thấp hơn mức tối thiểu." },
    { page: 12, loc: "Chương 2 › Điều 10", text: "Điều 10. Nghỉ học tạm thời và bảo lưu kết quả\nSinh viên có thể xin nghỉ học tạm thời vì lý do sức khỏe hoặc hoàn cảnh cá nhân; kết quả đã tích lũy được bảo lưu theo quyết định của nhà trường." },
    { page: 14, loc: "Chương 3 › Điều 11", text: "Điều 11. Đánh giá học phần\nĐiểm học phần gồm điểm quá trình và điểm thi kết thúc học phần; tỷ trọng từng thành phần được nêu trong đề cương học phần." },
    { page: 15, loc: "Chương 3 › Điều 12", text: "Điều 12. Cách tính điểm\nĐiểm trung bình tích lũy được tính theo công thức trung bình có trọng số của điểm học phần với số tín chỉ tương ứng." },
    { page: 16, loc: "Chương 3 › Điều 12 › Bảng quy đổi", is_table: true, text: "Điểm chữ | Điểm số | Thang điểm 4\nA | 8,5 – 10 | 4,0\nB | 7,0 – 8,4 | 3,0\nC | 5,5 – 6,9 | 2,0\nD | 4,0 – 5,4 | 1,0\nF | dưới 4,0 | 0" },
    { page: 17, loc: "Chương 3 › Điều 13", text: "Điều 13. Học lại và học cải thiện điểm\nHọc phần có điểm F phải học lại; sinh viên có thể đăng ký học cải thiện điểm, kết quả cao nhất được dùng để tính điểm trung bình tích lũy." },
    { page: 18, loc: "Chương 3 › Điều 14", text: "Điều 14. Xét và công nhận tốt nghiệp\nSinh viên được xét và công nhận tốt nghiệp khi tích lũy đủ học phần, điểm trung bình tích lũy toàn khóa đạt từ trung bình trở lên và không đang bị kỷ luật đình chỉ học tập." },
    { page: 19, loc: "Chương 3 › Điều 14 › Khoản 2", text: "Hằng năm, trường tổ chức xét tốt nghiệp theo các đợt. Lịch xét và hồ sơ cần nộp được thông báo trước cho sinh viên trên website của trường." },
    { page: 20, loc: "Chương 3 › Điều 15", text: "Điều 15. Cấp bằng tốt nghiệp\nBằng tốt nghiệp được cấp sau khi có quyết định công nhận tốt nghiệp; hạng tốt nghiệp xác định theo điểm trung bình tích lũy toàn khóa." },
    { page: 21, loc: "Chương 3 › Điều 16", text: "Điều 16. Cảnh báo học tập\nCảnh báo học tập được thực hiện sau mỗi học kỳ đối với sinh viên có kết quả học tập thấp hơn ngưỡng quy định." },
    { page: 23, loc: "Chương 4 › Điều 17", text: "Điều 17. Thôi học và buộc thôi học\nSinh viên có thể xin thôi học; sinh viên bị cảnh báo học tập nhiều lần liên tiếp có thể bị buộc thôi học theo quy định." },
    { page: 25, loc: "Chương 4 › Điều 19", text: "Điều 19. Chuyển ngành, chuyển cơ sở đào tạo\nSinh viên được xét chuyển ngành khi đáp ứng điều kiện về kết quả học tập và còn chỉ tiêu; hồ sơ nộp tại khoa tiếp nhận." },
    { page: 27, loc: "Chương 4 › Điều 21", text: "Điều 21. Học cùng lúc hai chương trình\nSinh viên có học lực khá trở lên có thể đăng ký học thêm chương trình thứ hai theo điều kiện của trường." },
    { page: 29, loc: "Chương 5 › Điều 23", text: "Điều 23. Khen thưởng\nSinh viên có thành tích học tập, rèn luyện xuất sắc được khen thưởng và xét học bổng theo quy định riêng." },
    { page: 30, loc: "Chương 5 › Điều 24", text: "Điều 24. Xử lý vi phạm\nSinh viên vi phạm quy chế thi, quy chế học tập bị xử lý theo mức độ từ nhắc nhở, cảnh cáo đến đình chỉ học tập." },
    { page: 32, loc: "Chương 6 › Điều 26", text: "Điều 26. Trách nhiệm của các đơn vị\nPhòng Đào tạo chủ trì tổ chức thực hiện quy chế; các khoa phối hợp triển khai và giải đáp thắc mắc cho sinh viên." },
    { page: 34, loc: "Phụ lục 1 › Bảng quy đổi điểm", is_table: true, text: "Bảng quy đổi điểm — Điểm chữ: A | Thang điểm 10: từ 8,5 đến 10 | Thang điểm 4: 4,0\nBảng quy đổi điểm — Điểm chữ: B+ | Thang điểm 10: từ 8,0 đến 8,4 | Thang điểm 4: 3,5" },
  ],
  [CHUAN_DAU_RA_DOC]: [
    { page: 2, loc: "Mục 1", text: "Mục 1. Phạm vi áp dụng\nQuy định này áp dụng cho sinh viên đại học hệ chính quy khi xét công nhận tốt nghiệp." },
    { page: 3, loc: "Mục 2", text: "Mục 2. Chuẩn đầu ra ngoại ngữ\nSinh viên phải đạt chuẩn đầu ra ngoại ngữ và tin học theo quy định của trường trước khi được xét công nhận tốt nghiệp." },
    { page: 4, loc: "Mục 3 › Bảng quy đổi chứng chỉ", is_table: true, text: "Chứng chỉ | Mức tối thiểu\nIELTS | 5.0\nTOEIC | 500\nVSTEP | Bậc 3" },
  ],
};

const MAX_GENERATED_CHUNKS = 200;

function toChunk(doc: StoredDocument, n: number, seed: ChunkSeed): Chunk {
  return {
    chunk_id: `chunk_${String(n).padStart(3, "0")}`,
    doc_id: doc.doc_id,
    page: seed.page,
    loc: seed.loc,
    tokens: Math.max(20, Math.round(seed.text.length / 3.2)),
    is_table: seed.is_table ?? false,
    text: seed.text,
  };
}

/** Chunk viết tay, đánh số rải theo trang để thứ tự khớp với tổng số chunk của tài liệu. */
function sampleChunksFor(doc: StoredDocument): Chunk[] {
  const seeds = SAMPLE_CHUNKS[doc.doc_id] ?? [];
  const total = Math.max(doc.chunks, seeds.length);
  const pages = Math.max(doc.pages, 1);
  let previous = 0;
  return seeds.map((seed) => {
    const n = Math.min(total, Math.max(previous + 1, Math.round(((seed.page - 1) * total) / pages) + 1));
    previous = n;
    return toChunk(doc, n, seed);
  });
}

/** Toàn bộ chunk của tài liệu: chunk viết tay + chunk sinh tự động cho đủ `doc.chunks`. */
function chunksFor(doc: StoredDocument): Chunk[] {
  const total = Math.min(doc.chunks, MAX_GENERATED_CHUNKS);
  if (total <= 0) return [];
  const samples = sampleChunksFor(doc);
  const used = new Set(samples.map((c) => c.chunk_id));
  const pages = Math.max(doc.pages, 1);
  const generated: Chunk[] = [];
  for (let n = 1; n <= total; n += 1) {
    const id = `chunk_${String(n).padStart(3, "0")}`;
    if (used.has(id)) continue;
    generated.push(
      toChunk(doc, n, {
        page: Math.min(pages, Math.ceil((n * pages) / total)),
        loc: `Mục ${n}`,
        text: `Nội dung đoạn ${n} của “${doc.title}” (dữ liệu mẫu).`,
      }),
    );
  }
  return [...samples, ...generated].sort((a, b) => a.chunk_id.localeCompare(b.chunk_id));
}

const CHUNK_FIRST_PAGE_SIZE = 5;
const CHUNK_NEXT_PAGE_SIZE = 10;

export async function mockListChunks(
  id: string,
  query: ChunkListQuery = {},
): Promise<ChunkListResponse> {
  await sleep(ADMIN_FAST_DELAY_MS);
  const doc = readDocs().find((d) => d.doc_id === id);
  if (!doc) throw new Error("Không tìm thấy tài liệu.");
  const q = normalize(query.q?.trim() ?? "");
  const all = chunksFor(doc)
    .filter((c) => (query.type === "table" ? c.is_table : query.type === "text" ? !c.is_table : true))
    .filter((c) => !query.page || c.page === query.page)
    .filter((c) => !q || normalize(c.text).includes(q));
  const start = Number(query.cursor ?? 0) || 0;
  const size = start === 0 ? CHUNK_FIRST_PAGE_SIZE : CHUNK_NEXT_PAGE_SIZE;
  const items = all.slice(start, start + size);
  const next = start + size;
  return { items, total: all.length, next_cursor: next < all.length ? String(next) : undefined };
}

export async function mockRetrieveTest(req: {
  question: string;
  doc_id?: string;
}): Promise<{ items: RetrieveTestHit[] }> {
  await sleep(UPLOAD_DELAY_MS);
  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error("Không kết nối được tới Qdrant (localhost:6333). Kiểm tra dịch vụ rồi thử lại.");
  }
  const words = normalize(req.question)
    .split(" ")
    .filter((w) => w.length > 1);
  const docs = readDocs().filter(
    (d) => d.status === "indexed" && (!req.doc_id || d.doc_id === req.doc_id),
  );
  const scored = docs.flatMap((doc) =>
    (SAMPLE_CHUNKS[doc.doc_id] ? sampleChunksFor(doc) : chunksFor(doc).slice(0, 10)).map((chunk) => {
      const text = normalize(chunk.text);
      const hits = words.filter((w) => text.includes(w)).length;
      const ratio = words.length ? hits / words.length : 0;
      return { doc, chunk, score: Math.min(0.97, 0.2 + ratio * 0.75) };
    }),
  );
  scored.sort((a, b) => b.score - a.score);
  return {
    items: scored.slice(0, 5).map(({ doc, chunk, score }, i) => ({
      rank: i + 1,
      chunk_id: chunk.chunk_id,
      doc_id: doc.doc_id,
      doc_title: doc.title,
      page: chunk.page,
      loc: chunk.loc,
      excerpt: chunk.text.length > 220 ? `${chunk.text.slice(0, 219)}…` : chunk.text,
      rerank_score: Number(score.toFixed(2)),
    })),
  };
}

// --- Phản hồi -------------------------------------------------------------

function seedFeedback(): AdminFeedbackItem[] {
  const day = 24 * 60;
  const chunk = (doc: string, n: number, page: number, score: number) => ({
    chunk_id: `chunk_${String(n).padStart(3, "0")}`,
    doc_id: docId(doc),
    doc_title: doc,
    page,
    rerank_score: score,
  });
  return [
    {
      feedback_id: "fb_seed_1",
      message_id: "msg_8f21",
      vote: "down",
      reason: "missing_info",
      note: "Không nêu mức cụ thể cho ngành KHMT.",
      question: "Chuẩn đầu ra tiếng Anh của ngành KHMT là gì?",
      answer:
        "Sinh viên phải đạt chuẩn đầu ra ngoại ngữ theo quy định của chương trình đào tạo trước khi được xét tốt nghiệp. [2]",
      created_at: ago(15),
      handled: false,
      in_test_set: false,
      chunks: [chunk("Quy định chuẩn đầu ra ngoại ngữ, tin học", 7, 3, 0.81)],
    },
    {
      feedback_id: "fb_seed_2",
      message_id: "msg_7c10",
      vote: "down",
      reason: "outdated",
      question: "Học phí một tín chỉ năm học này là bao nhiêu?",
      answer:
        "Học phí được tính theo số tín chỉ sinh viên đăng ký và áp dụng theo thông báo học phí của từng năm học. [1]",
      created_at: ago(50),
      handled: false,
      in_test_set: false,
      chunks: [chunk("Biểu học phí năm học [NĂM HỌC]", 2, 1, 0.77)],
    },
    {
      feedback_id: "fb_seed_3",
      message_id: "msg_6a02",
      vote: "up",
      question: "Điều kiện để được xét tốt nghiệp là gì?",
      answer:
        "Sinh viên được xét tốt nghiệp khi tích lũy đủ học phần, đạt điểm trung bình tích lũy toàn khóa từ mức trung bình trở lên, đạt chuẩn đầu ra và không bị kỷ luật đình chỉ học tập. [1][2]",
      created_at: ago(1 * day + 120),
      handled: false,
      in_test_set: false,
      chunks: [
        chunk("Quy chế đào tạo trình độ đại học", 14, 18, 0.92),
        chunk("Quy định chuẩn đầu ra ngoại ngữ, tin học", 7, 3, 0.81),
      ],
    },
    {
      feedback_id: "fb_seed_4",
      message_id: "msg_5d33",
      vote: "down",
      reason: "other",
      note: "Mẫu đơn trong câu trả lời đã cũ, em thấy khác với mẫu đang dùng.",
      question: "Thủ tục xin bảo lưu kết quả học tập?",
      answer:
        "Sinh viên nộp đơn xin bảo lưu tại Phòng Đào tạo trong thời hạn quy định và chờ quyết định của nhà trường. [1]",
      created_at: ago(1 * day + 400),
      handled: false,
      in_test_set: false,
      chunks: [chunk("Quy chế đào tạo trình độ đại học", 5, 9, 0.64)],
    },
    {
      feedback_id: "fb_seed_5",
      message_id: "msg_4b77",
      vote: "up",
      question: "Mỗi kỳ được đăng ký tối đa bao nhiêu tín chỉ?",
      answer: "Mức tối đa phụ thuộc vào học lực của sinh viên ở học kỳ liền trước. [1]",
      created_at: ago(7 * day),
      handled: false,
      in_test_set: false,
      chunks: [chunk("Quy chế đào tạo trình độ đại học", 3, 9, 0.88)],
    },
    {
      feedback_id: "fb_seed_6",
      message_id: "msg_3e19",
      vote: "down",
      reason: "wrong_info",
      question: "Khi nào sinh viên bị cảnh báo học tập?",
      answer:
        "Sinh viên bị cảnh báo học tập khi điểm trung bình học kỳ hoặc điểm trung bình tích lũy thấp hơn ngưỡng cảnh báo của trường. [1]",
      created_at: ago(8 * day),
      handled: true,
      in_test_set: true,
      chunks: [chunk("Quy chế đào tạo trình độ đại học", 8, 21, 0.79)],
    },
  ];
}

function readAdminFeedback(): AdminFeedbackItem[] {
  const stored = getMockStorage<AdminFeedbackItem[] | null>(ADMIN_FEEDBACK_KEY, null);
  if (stored) return stored;
  const seeded = seedFeedback();
  setMockStorage(ADMIN_FEEDBACK_KEY, seeded);
  return seeded;
}

function writeAdminFeedback(list: AdminFeedbackItem[]): void {
  setMockStorage(ADMIN_FEEDBACK_KEY, list);
  emitAdminChanged();
}

export async function mockListFeedback(tab: FeedbackTab = "all"): Promise<AdminFeedbackList> {
  const all = [...readAdminFeedback()].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  const unhandled = all.filter((f) => f.vote === "down" && !f.handled).length;
  const items = all.filter((f) => {
    if (tab === "down") return f.vote === "down";
    if (tab === "up") return f.vote === "up";
    if (tab === "unhandled") return f.vote === "down" && !f.handled;
    return true;
  });
  return {
    items,
    stats: {
      total: all.length,
      up_count: all.filter((f) => f.vote === "up").length,
      down_count: all.filter((f) => f.vote === "down").length,
      unhandled_wrong_count: unhandled,
    },
    unhandled_wrong_count: unhandled,
  };
}

export async function mockUpdateFeedback(
  id: string,
  patch: { handled?: boolean; in_test_set?: boolean },
): Promise<AdminFeedbackItem> {
  await sleep(ADMIN_FAST_DELAY_MS);
  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error(MOCK_CONNECTION_ERROR);
  }
  const list = readAdminFeedback();
  const found = list.find((f) => f.feedback_id === id);
  if (!found) throw new Error("Không tìm thấy phản hồi.");
  const updated = { ...found, ...patch };
  writeAdminFeedback(list.map((f) => (f.feedback_id === id ? updated : f)));
  return updated;
}

function csvCell(value: string | number | undefined): string {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

/** Xuất toàn bộ phản hồi thành CSV UTF-8 có BOM (để Excel đọc đúng tiếng Việt). */
export async function mockExportFeedbackCsv(): Promise<string> {
  await sleep(UPLOAD_DELAY_MS);
  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error(MOCK_CONNECTION_ERROR);
  }
  const header = [
    "feedback_id",
    "message_id",
    "danh_gia",
    "ly_do",
    "ghi_chu",
    "cau_hoi",
    "cau_tra_loi",
    "thoi_gian",
    "da_xu_ly",
    "trong_bo_test",
    "chunk_da_dung",
  ];
  const rows = readAdminFeedback().map((f) =>
    [
      f.feedback_id,
      f.message_id,
      f.vote === "up" ? "Đúng" : "Sai",
      f.reason ?? "",
      f.note ?? "",
      f.question,
      f.answer,
      f.created_at,
      f.handled ? "Có" : "Không",
      f.in_test_set ? "Có" : "Không",
      f.chunks.map((c) => `${c.doc_title} / ${c.chunk_id} / trang ${c.page} / rerank ${c.rerank_score}`).join("; "),
    ]
      .map(csvCell)
      .join(","),
  );
  const csv = [header.map(csvCell).join(","), ...rows].join("\r\n");
  return `\uFEFF${csv}`;
}

/**
 * Dữ liệu giả cho giai đoạn mock-first. NỘI DUNG CHỈ MINH HỌA, không phải quy định thật của trường.
 * State lưu trong localStorage với tiền tố `sar_mock_` (xem lib/storage.ts).
 */
import { SUGGESTED_QUESTION_GROUPS } from "@/lib/constants";
import { clearAllMockStorage, getMockStorage, setMockStorage } from "@/lib/storage";
import type {
  AnswerMessage,
  Citation,
  ConversationDetail,
  ConversationSummary,
  FeedbackIn,
  FeedbackOut,
  SourceType,
} from "@/lib/types";

export const MOCK_DELAY_MS = 1500;
export const CONVERSATIONS_CHANGED_EVENT = "sar:conversations-changed";

const CONVERSATIONS_KEY = "conversations";
const FEEDBACK_KEY = "feedback";
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

interface StoredFeedback extends FeedbackIn {
  feedback_id: string;
  created_at: string;
  handled: boolean;
  in_test_set: boolean;
}

/** Lưu/đổi đánh giá cho một câu trả lời (mỗi message_id một đánh giá). */
export async function mockSendFeedback(input: FeedbackIn): Promise<FeedbackOut> {
  await sleep(FEEDBACK_DELAY_MS);
  if (process.env.NEXT_PUBLIC_MOCK_ERROR === "true") {
    throw new Error(MOCK_CONNECTION_ERROR);
  }
  const list = getMockStorage<StoredFeedback[]>(FEEDBACK_KEY, []);
  const existing = list.find((f) => f.message_id === input.message_id);
  const record: StoredFeedback = {
    ...input,
    feedback_id: existing?.feedback_id ?? newId("fb"),
    created_at: new Date().toISOString(),
    handled: false,
    in_test_set: existing?.in_test_set ?? false,
  };
  setMockStorage(FEEDBACK_KEY, [record, ...list.filter((f) => f.message_id !== input.message_id)]);

  writeAll(
    readAll().map((c) => ({
      ...c,
      messages: c.messages.map((m) =>
        m.message_id === input.message_id
          ? {
              ...m,
              feedback: {
                vote: input.vote,
                reason: input.reason,
                note: input.note,
              },
            }
          : m,
      ),
    })),
  );
  return { feedback_id: record.feedback_id, status: "received" };
}

/** Xóa toàn bộ state mock (sar_mock_*); lần truy cập sau dữ liệu mẫu được tạo lại. */
export function resetMockData(): void {
  clearAllMockStorage();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CONVERSATIONS_CHANGED_EVENT));
  }
}

import type { DocCategory, FeedbackReason, IndexStep } from "./types";

export interface DocCategoryOption {
  value: DocCategory;
  label: string;
}

export const DOC_CATEGORIES: ReadonlyArray<DocCategoryOption> = [
  { value: "quy_che", label: "Quy chế" },
  { value: "ctdt", label: "Chương trình đào tạo" },
  { value: "quy_trinh", label: "Quy trình – thủ tục" },
  { value: "ke_hoach", label: "Kế hoạch đào tạo" },
  { value: "hoc_phi", label: "Học phí" },
  { value: "hoc_bong", label: "Học bổng" },
  { value: "mon_thay_the", label: "Môn học thay thế" },
  { value: "lien_he", label: "Liên hệ" },
  { value: "lich_thi", label: "Lịch thi" },
  { value: "tkb", label: "Thời khóa biểu" },
  { value: "thong_bao", label: "Thông báo" },
  { value: "khac", label: "Khác" },
];

export const DOC_CATEGORY_LABELS: Record<DocCategory, string> = {
  quy_che: "Quy chế",
  ctdt: "Chương trình đào tạo",
  quy_trinh: "Quy trình – thủ tục",
  ke_hoach: "Kế hoạch đào tạo",
  hoc_phi: "Học phí",
  hoc_bong: "Học bổng",
  mon_thay_the: "Môn học thay thế",
  lien_he: "Liên hệ",
  lich_thi: "Lịch thi",
  tkb: "Thời khóa biểu",
  thong_bao: "Thông báo",
  khac: "Khác",
};

export function getDocCategoryLabel(category: string): string {
  return DOC_CATEGORY_LABELS[category as DocCategory] ?? category;
}

export interface FeedbackReasonOption {
  value: FeedbackReason;
  label: string;
  shortLabel: string;
}

export const FEEDBACK_REASONS: ReadonlyArray<FeedbackReasonOption> = [
  { value: "wrong_info", label: "Thông tin sai", shortLabel: "Thông tin sai" },
  {
    value: "irrelevant_source",
    label: "Nguồn không liên quan",
    shortLabel: "Nguồn không liên quan",
  },
  {
    value: "missing_info",
    label: "Thiếu thông tin",
    shortLabel: "Thiếu thông tin",
  },
  { value: "outdated", label: "Thông tin đã cũ", shortLabel: "Thông tin đã cũ" },
  { value: "other", label: "Khác (tự nhập)", shortLabel: "Khác" },
];

export const FEEDBACK_REASON_LABELS: Record<FeedbackReason, string> = {
  wrong_info: "Thông tin sai",
  irrelevant_source: "Nguồn không liên quan",
  missing_info: "Thiếu thông tin",
  outdated: "Thông tin đã cũ",
  other: "Khác",
};

export type SuggestedGroupIcon =
  | "graduation-cap"
  | "credit-card"
  | "calendar"
  | "clipboard";

export interface SuggestedQuestionGroup {
  id: string;
  title: string;
  icon: SuggestedGroupIcon;
  questions: ReadonlyArray<string>;
}

export const SUGGESTED_QUESTION_GROUPS: ReadonlyArray<SuggestedQuestionGroup> = [
  {
    id: "quy-che-tot-nghiep",
    title: "Quy chế & tốt nghiệp",
    icon: "graduation-cap",
    questions: [
      "Điều kiện để được xét tốt nghiệp là gì?",
      "Điểm trung bình tích lũy được tính thế nào?",
      "Khi nào sinh viên bị cảnh báo học tập?",
    ],
  },
  {
    id: "hoc-phi-hoc-bong",
    title: "Học phí & học bổng",
    icon: "credit-card",
    questions: [
      "Học phí một tín chỉ năm học này là bao nhiêu?",
      "Điều kiện nhận học bổng khuyến khích học tập?",
      "Hạn đóng học phí học kỳ này là khi nào?",
    ],
  },
  {
    id: "dang-ky-hoc-phan",
    title: "Đăng ký học phần",
    icon: "calendar",
    questions: [
      "Thời gian đăng ký học phần học kỳ tới?",
      "Mỗi kỳ được đăng ký tối đa bao nhiêu tín chỉ?",
      "Làm sao để rút bớt học phần đã đăng ký?",
    ],
  },
  {
    id: "thu-tuc-hanh-chinh",
    title: "Thủ tục hành chính",
    icon: "clipboard",
    questions: [
      "Thủ tục xin bảo lưu kết quả học tập?",
      "Cách xin giấy xác nhận sinh viên?",
      "Hồ sơ chuyển ngành gồm những gì?",
    ],
  },
];

export const INDEX_STEP_LABELS: Record<IndexStep, string> = {
  1: "Trích xuất văn bản (PDF / OCR)",
  2: "Chia chunk (bảng lớn: lặp header theo dòng)",
  3: "Tạo embedding",
  4: "Lưu vào Qdrant kèm doc_id, version",
};

export const INDEX_STEP_SHORT_LABELS: Record<IndexStep, string> = {
  1: "Trích xuất văn bản",
  2: "Chia chunk",
  3: "Tạo embedding",
  4: "Lưu vào Qdrant",
};

import type { Metadata } from "next";
import { FeedbackManager } from "@/components/admin/FeedbackManager";

export const metadata: Metadata = {
  title: "Phản hồi — Quản trị Trợ lý Học vụ",
};

// Trang quản trị chỉ hiển thị sau khi AdminAuthGuard đọc token ở client (localStorage), nên
// static shell không chứa nội dung trang — cố ý để không lộ giao diện admin trước khi kiểm tra
// đăng nhập. Vì vậy tắt kiểm tra "instant navigation" cho segment này (cách [ignore] trong tài liệu Next).
export const instant = false;

export default function AdminFeedbackPage() {
  return <FeedbackManager />;
}

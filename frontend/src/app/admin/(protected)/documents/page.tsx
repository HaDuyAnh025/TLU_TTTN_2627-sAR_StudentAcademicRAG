import type { Metadata } from "next";
import { DocumentsView } from "@/components/admin/DocumentsView";

export const metadata: Metadata = {
  title: "Tài liệu — Quản trị Trợ lý Học vụ",
};

// Trang quản trị chỉ hiển thị sau khi AdminAuthGuard đọc token ở client (localStorage), nên
// static shell không chứa nội dung trang — cố ý để không lộ giao diện admin trước khi kiểm tra
// đăng nhập. Vì vậy tắt kiểm tra "instant navigation" cho segment này (cách [ignore] trong tài liệu Next).
export const instant = false;

export default function AdminDocumentsPage() {
  return <DocumentsView />;
}

import { Suspense } from "react";
import { AdminAuthGuard } from "@/components/admin/AdminAuthGuard";
import { DocumentStatusToaster } from "@/components/admin/DocumentStatusToaster";
import { SidebarAdmin } from "@/components/layout/SidebarAdmin";

function SidebarFallback() {
  return (
    <aside
      aria-hidden="true"
      className="hidden w-sidebar-admin shrink-0 border-r border-border-default bg-bg-surface md:block"
    />
  );
}

// Trang quản trị chỉ hiển thị sau khi AdminAuthGuard đọc token ở client (localStorage), nên
// static shell không chứa nội dung trang — cố ý để không lộ giao diện admin trước khi kiểm tra
// đăng nhập. Vì vậy tắt kiểm tra "instant navigation" cho segment này (cách [ignore] trong tài liệu Next).
export const instant = false;

export default function AdminProtectedLayout({ children }: LayoutProps<"/admin">) {
  return (
    <AdminAuthGuard>
      <div className="flex flex-1 flex-col md:flex-row">
        <Suspense fallback={<SidebarFallback />}>
          <SidebarAdmin />
        </Suspense>
        <main className="min-w-0 flex-1 p-6 md:p-8">{children}</main>
      </div>
      <DocumentStatusToaster />
    </AdminAuthGuard>
  );
}

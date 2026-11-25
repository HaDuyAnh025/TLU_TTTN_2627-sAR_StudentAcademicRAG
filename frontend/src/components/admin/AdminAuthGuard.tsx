"use client";

import { useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { getAdminToken, subscribeAdminToken } from "@/services/admin.service";

/**
 * Chặn các trang quản trị khi chưa có token (sar_admin_token) → chuyển về /admin/login.
 * Lưu ý: đây chỉ là chặn ở giao diện; backend thật vẫn phải kiểm tra JWT ở mọi endpoint admin.
 */
export function AdminAuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  // undefined = chưa hydrate (server); null = chưa đăng nhập; string = đã đăng nhập.
  const token = useSyncExternalStore(subscribeAdminToken, getAdminToken, () => undefined);

  useEffect(() => {
    if (token === null) router.replace("/admin/login");
  }, [token, router]);

  if (!token) {
    return (
      <div role="status" className="p-8 text-body text-text-muted">
        Đang kiểm tra phiên đăng nhập…
      </div>
    );
  }
  return <>{children}</>;
}

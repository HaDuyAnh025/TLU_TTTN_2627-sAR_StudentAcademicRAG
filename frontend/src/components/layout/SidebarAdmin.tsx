"use client";

import clsx from "clsx";
import { ExternalLink, FileText, LogOut, MessageSquare } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { listFeedback, logout, subscribeAdminData } from "@/services/admin.service";

const NAV_ITEM =
  "flex min-h-control items-center gap-3 rounded-sm px-3 text-body-sm transition-colors";

export function SidebarAdmin() {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const [unhandled, setUnhandled] = useState(0);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    function refresh() {
      listFeedback("all").then((res) => {
        if (!cancelled) setUnhandled(res.unhandled_wrong_count);
      });
    }
    refresh();
    const unsubscribe = subscribeAdminData(refresh);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  function handleLogout() {
    logout();
    setConfirmOpen(false);
    toast.info("Đã đăng xuất", "Bạn đã thoát khỏi trang quản trị.");
    router.replace("/admin/login");
  }

  const items = [
    { href: "/admin/documents", label: "Tài liệu", icon: FileText, badge: 0 },
    { href: "/admin/feedback", label: "Phản hồi", icon: MessageSquare, badge: unhandled },
  ];

  return (
    <aside
      aria-label="Menu quản trị"
      className="flex w-full shrink-0 flex-col border-b border-border-default bg-bg-surface p-4 lg:sticky lg:top-0 lg:h-screen lg:w-sidebar-admin lg:border-b-0 lg:border-r"
    >
      <Link href="/admin/documents" aria-label="Trợ lý Học vụ — Quản trị" className="rounded-md">
        <BrandLogo subtitle="Quản trị" />
      </Link>

      <nav aria-label="Mục quản trị" className="mt-6 flex flex-col gap-1">
        {items.map(({ href, label, icon: Icon, badge }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={clsx(
                NAV_ITEM,
                active
                  ? "bg-brand-navy-soft font-semibold text-brand-navy"
                  : "text-text-secondary hover:bg-bg-hover",
              )}
            >
              <Icon size={18} aria-hidden="true" className="shrink-0" />
              <span className="flex-1">{label}</span>
              {badge > 0 ? (
                <span
                  aria-label={`${badge} phản hồi sai chưa xử lý`}
                  className="rounded-full bg-error-bg px-2 py-0.5 text-caption-sm font-semibold text-error-text"
                >
                  {badge}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      <div className="mt-6 flex flex-col gap-1 border-t border-border-divider pt-4 lg:mt-auto">
        <Link
          href="/"
          target="_blank"
          rel="noopener noreferrer"
          className={clsx(NAV_ITEM, "text-text-secondary hover:bg-bg-hover")}
        >
          <ExternalLink size={18} aria-hidden="true" className="shrink-0" />
          Mở trang sinh viên
        </Link>
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          className={clsx(NAV_ITEM, "cursor-pointer text-left text-text-secondary hover:bg-bg-hover")}
        >
          <LogOut size={18} aria-hidden="true" className="shrink-0" />
          Đăng xuất
        </button>
      </div>

      <Dialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Đăng xuất khỏi trang quản trị?"
        description="Bạn cần đăng nhập lại để tiếp tục quản lý tài liệu và phản hồi."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Hủy
            </Button>
            <Button onClick={handleLogout}>Đăng xuất</Button>
          </>
        }
      />
    </aside>
  );
}

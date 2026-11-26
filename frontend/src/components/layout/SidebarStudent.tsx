"use client";

import clsx from "clsx";
import { Info, MessageSquare, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { groupConversationsByDate } from "@/lib/date-groups";
import { getOrCreateSessionId } from "@/lib/storage";
import type { ConversationSummary } from "@/lib/types";
import {
  deleteAllConversations,
  listConversations,
  subscribeConversations,
} from "@/services/chat.service";

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .toLowerCase();
}

export function SidebarStudent() {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(() => {
    listConversations(getOrCreateSessionId()).then((list) => {
      setConversations(list);
      setLoaded(true);
    });
  }, []);

  useEffect(() => {
    refresh();
    return subscribeConversations(refresh);
  }, [refresh]);

  const filtered = useMemo(() => {
    const q = normalize(query.trim());
    if (!q) return conversations;
    return conversations.filter((c) => normalize(c.title).includes(q));
  }, [conversations, query]);

  const groups = useMemo(() => groupConversationsByDate(filtered), [filtered]);

  function handleNewConversation() {
    toast.info(
      "Bạn đang ở cuộc trò chuyện mới",
      "Nhập câu hỏi hoặc chọn một gợi ý bên dưới để bắt đầu.",
    );
    if (pathname !== "/") router.push("/");
  }

  function handleClearAllClick() {
    if (conversations.length === 0) {
      toast.info("Chưa có lịch sử", "Trình duyệt này chưa lưu cuộc trò chuyện nào để xóa.");
      return;
    }
    setConfirmOpen(true);
  }

  async function handleConfirmClearAll() {
    setDeleting(true);
    try {
      await deleteAllConversations(getOrCreateSessionId());
      setConfirmOpen(false);
      toast.success("Đã xóa toàn bộ lịch sử", "Các cuộc trò chuyện trên trình duyệt này đã được xóa.");
      if (pathname !== "/") router.push("/");
    } catch {
      toast.error("Không xóa được lịch sử", "Vui lòng thử lại sau.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <aside
      aria-label="Lịch sử trò chuyện"
      className={clsx(
        "flex w-full shrink-0 flex-col border-b border-border-default bg-bg-surface",
        "lg:sticky lg:top-0 lg:h-screen lg:w-sidebar-student lg:border-b-0 lg:border-r",
      )}
    >
      <div className="flex flex-col gap-4 p-4 pb-3">
        <Link href="/" aria-label="Trợ lý Học vụ — về trang chủ" className="rounded-md">
          <BrandLogo />
        </Link>
        <Button
          fullWidth
          icon={<Plus size={18} aria-hidden="true" />}
          onClick={handleNewConversation}
        >
          Cuộc trò chuyện mới
        </Button>
        <div className="relative">
          <Search
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Tìm cuộc trò chuyện"
            aria-label="Tìm cuộc trò chuyện"
            className="h-control w-full rounded-md border border-border-default bg-bg-page pl-10 pr-3 text-body-sm text-text-primary placeholder:text-text-muted"
          />
        </div>
      </div>

      <nav
        aria-label="Danh sách cuộc trò chuyện"
        className="min-h-0 max-h-[40vh] flex-1 overflow-y-auto px-4 pb-4 lg:max-h-none"
      >
        {loaded && conversations.length === 0 ? (
          <p className="px-2 py-3 text-body-sm text-text-muted">Chưa có cuộc trò chuyện nào.</p>
        ) : null}
        {loaded && conversations.length > 0 && groups.length === 0 ? (
          <p role="status" className="px-2 py-3 text-body-sm text-text-muted">
            Không tìm thấy cuộc trò chuyện nào khớp “{query.trim()}”.
          </p>
        ) : null}
        {groups.map((group) => (
          <section key={group.id} className="mt-3 first:mt-0">
            <h2 className="px-2 py-2 text-overline uppercase text-text-label">{group.label}</h2>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const href = `/c/${item.conversation_id}`;
                const active = pathname === href;
                return (
                  <li key={item.conversation_id}>
                    <Link
                      href={href}
                      aria-current={active ? "page" : undefined}
                      className={clsx(
                        "flex h-control-sm items-center gap-3 rounded-sm px-2.5 text-body-sm transition-colors",
                        active
                          ? "bg-brand-navy-soft font-semibold text-brand-navy"
                          : "text-text-secondary hover:bg-bg-hover",
                      )}
                    >
                      <MessageSquare size={16} aria-hidden="true" className="shrink-0" />
                      <span className="truncate" title={item.title}>
                        {item.title}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>

      <div className="flex flex-col gap-3 border-t border-border-divider p-4">
        <p className="flex items-start gap-2 text-caption-sm text-text-muted">
          <Info size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
          Không cần đăng nhập. Lịch sử hội thoại chỉ được lưu trên trình duyệt này.
        </p>
        <Button
          variant="secondary"
          size="sm"
          fullWidth
          icon={<Trash2 size={16} aria-hidden="true" />}
          onClick={handleClearAllClick}
        >
          Xóa toàn bộ lịch sử
        </Button>
      </div>

      <Dialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Xóa toàn bộ lịch sử?"
        description={`${conversations.length} cuộc trò chuyện được lưu trên trình duyệt này sẽ bị xóa. Không thể hoàn tác.`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Hủy
            </Button>
            <Button variant="danger" loading={deleting} onClick={handleConfirmClearAll}>
              Xóa toàn bộ
            </Button>
          </>
        }
      />
    </aside>
  );
}

"use client";

import clsx from "clsx";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import type { Chunk, ChunkTypeFilter } from "@/lib/types";
import { listChunks } from "@/services/admin.service";

const TYPE_TABS: ReadonlyArray<{ value: ChunkTypeFilter; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "text", label: "Văn bản" },
  { value: "table", label: "Bảng" },
];

export interface ChunkListPanelProps {
  docId: string;
  /** Đổi giá trị này để tải lại danh sách (ví dụ sau khi re-index xong). */
  refreshKey: string;
}

export function ChunkListPanel({ docId, refreshKey }: ChunkListPanelProps) {
  const toast = useToast();
  const [type, setType] = useState<ChunkTypeFilter>("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState("");
  const [items, setItems] = useState<Chunk[]>([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);

  const pageNumber = Number(page) > 0 ? Number(page) : undefined;
  const filtering = type !== "all" || q.trim() !== "" || page.trim() !== "";

  useEffect(() => {
    let cancelled = false;
    // Chờ 300ms sau lần gõ cuối để không gọi liên tục.
    const timer = setTimeout(() => {
      setLoading(true);
      setError(false);
      listChunks(docId, { type, q, page: pageNumber })
        .then((res) => {
          if (cancelled) return;
          setItems(res.items);
          setTotal(res.total);
          setNextCursor(res.next_cursor);
          setLoading(false);
        })
        .catch(() => {
          if (cancelled) return;
          setError(true);
          setLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [docId, type, q, pageNumber, refreshKey]);

  async function handleLoadMore() {
    if (!nextCursor) {
      toast.info("Đã hiện hết chunk", `Đang hiện ${items.length} / ${total} chunk.`);
      return;
    }
    setLoadingMore(true);
    try {
      const res = await listChunks(docId, { type, q, page: pageNumber, cursor: nextCursor });
      setItems((prev) => [...prev, ...res.items]);
      setTotal(res.total);
      setNextCursor(res.next_cursor);
    } catch {
      toast.error("Không tải thêm được chunk", "Vui lòng thử lại.");
    } finally {
      setLoadingMore(false);
    }
  }

  function clearFilters() {
    setType("all");
    setQ("");
    setPage("");
  }

  return (
    <section aria-labelledby="chunk-panel-title" className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="chunk-panel-title" className="text-h2 text-text-primary">
          Chunk của tài liệu
        </h2>
        <div role="group" aria-label="Loại chunk" className="inline-flex gap-1 rounded-md bg-bg-subtle p-1">
          {TYPE_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              aria-pressed={type === tab.value}
              onClick={() => setType(tab.value)}
              className={clsx(
                "h-control-sm cursor-pointer rounded-sm px-4 text-body-sm",
                type === tab.value
                  ? "bg-bg-surface font-semibold text-text-primary shadow-sm"
                  : "text-text-tertiary hover:text-text-primary",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 flex gap-3">
        <div className="relative min-w-0 flex-1">
          <Search
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm nội dung trong chunk"
            aria-label="Tìm nội dung trong chunk"
            className="h-control w-full rounded-md border border-border-default bg-bg-surface pl-10 pr-3 text-body-sm text-text-primary placeholder:text-text-muted"
          />
        </div>
        <input
          type="number"
          min={1}
          inputMode="numeric"
          value={page}
          onChange={(e) => setPage(e.target.value)}
          placeholder="Trang"
          aria-label="Lọc theo số trang"
          className="h-control w-[110px] shrink-0 rounded-md border border-border-default bg-bg-surface px-3 text-body-sm text-text-primary placeholder:text-text-muted"
        />
      </div>

      <div className="mt-4 flex flex-col gap-3" aria-busy={loading}>
        {loading ? (
          <p role="status" className="py-6 text-center text-body-sm text-text-muted">
            Đang tải chunk…
          </p>
        ) : error ? (
          <p role="alert" className="rounded-lg border border-error-border bg-error-bg px-4 py-3 text-body-sm text-error-text">
            Không tải được danh sách chunk. Vui lòng thử lại sau.
          </p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-border-default bg-bg-surface px-6 py-10 text-center">
            <p className="text-body-sm text-text-secondary">
              {filtering
                ? "Không có chunk nào khớp bộ lọc."
                : "Tài liệu này chưa có chunk (chưa xử lý xong hoặc xử lý lỗi)."}
            </p>
            {filtering ? (
              <Button variant="secondary" size="sm" onClick={clearFilters}>
                Xóa bộ lọc
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            {items.map((chunk) => (
              <article
                key={chunk.chunk_id}
                className="rounded-lg border border-border-default bg-bg-surface p-4"
              >
                <header className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-text-muted">
                  <span className="font-mono text-body-sm font-bold text-text-primary">
                    {chunk.chunk_id}
                  </span>
                  <span>· Trang {chunk.page}</span>
                  <span>· {chunk.loc}</span>
                  {chunk.is_table ? (
                    <Badge tone="processing" icon={false} className="rounded-xs">
                      Bảng · 1 dòng = 1 câu
                    </Badge>
                  ) : null}
                  <span className="ml-auto">{chunk.tokens} token</span>
                </header>
                <p className="mt-2 whitespace-pre-line text-body-sm text-text-primary">{chunk.text}</p>
              </article>
            ))}
            <div className="flex justify-center pt-1">
              <Button variant="secondary" loading={loadingMore} onClick={handleLoadMore}>
                Xem thêm chunk (đang hiện {items.length} / {total})
              </Button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

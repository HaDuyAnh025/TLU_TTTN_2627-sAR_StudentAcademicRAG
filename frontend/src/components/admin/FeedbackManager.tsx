"use client";

import clsx from "clsx";
import { Check, ChevronRight, ClipboardCheck, Download, File as FileIcon, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { StatCard } from "@/components/ui/StatCard";
import { useToast } from "@/components/ui/Toast";
import { FEEDBACK_REASON_LABELS } from "@/lib/constants";
import { formatFeedbackTime } from "@/lib/date-groups";
import type { AdminFeedbackItem, FeedbackStats, FeedbackTab } from "@/lib/types";
import {
  exportFeedbackCsv,
  listFeedback,
  subscribeAdminData,
  updateFeedback,
} from "@/services/admin.service";

const TABS: ReadonlyArray<{ value: FeedbackTab; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "down", label: "Sai" },
  { value: "up", label: "Đúng" },
  { value: "unhandled", label: "Chưa xử lý" },
];

const EMPTY_MESSAGES: Record<FeedbackTab, string> = {
  all: "Chưa có phản hồi nào từ sinh viên.",
  down: "Chưa có đánh giá Sai nào.",
  up: "Chưa có đánh giá Đúng nào.",
  unhandled: "Không còn phản hồi Sai nào chưa xử lý.",
};

const EMPTY_STATS: FeedbackStats = {
  total: 0,
  up_count: 0,
  down_count: 0,
  unhandled_wrong_count: 0,
};

function reasonText(item: AdminFeedbackItem): string {
  return item.reason ? FEEDBACK_REASON_LABELS[item.reason] : "Không nêu lý do";
}

export function FeedbackManager() {
  const toast = useToast();
  const [tab, setTab] = useState<FeedbackTab>("all");
  const [items, setItems] = useState<AdminFeedbackItem[]>([]);
  const [stats, setStats] = useState<FeedbackStats>(EMPTY_STATS);
  const [loaded, setLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState<"handled" | "test" | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    function load() {
      listFeedback(tab).then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setStats(res.stats);
        setLoaded(true);
      });
    }
    load();
    const unsubscribe = subscribeAdminData(load);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [tab]);

  // Mục đang xem: theo lựa chọn, nếu không còn trong tab thì lấy mục đầu tiên.
  const selected = items.find((f) => f.feedback_id === selectedId) ?? items[0] ?? null;

  async function toggleHandled(item: AdminFeedbackItem) {
    setSaving("handled");
    try {
      await updateFeedback(item.feedback_id, { handled: !item.handled });
      if (item.handled) {
        toast.info("Đã mở lại phản hồi", "Phản hồi này được tính là chưa xử lý.");
      } else {
        toast.success("Đã đánh dấu đã xử lý", "Phản hồi này không còn trong mục Chưa xử lý.");
      }
    } catch {
      toast.error("Không lưu được thay đổi", "Vui lòng thử lại.");
    } finally {
      setSaving(null);
    }
  }

  async function toggleTestSet(item: AdminFeedbackItem) {
    setSaving("test");
    try {
      await updateFeedback(item.feedback_id, { in_test_set: !item.in_test_set });
      if (item.in_test_set) {
        toast.info("Đã bỏ khỏi bộ test", "Câu hỏi này không còn được dùng khi đánh giá hệ thống.");
      } else {
        toast.success(
          "Đã thêm vào bộ test",
          "Câu hỏi sẽ được dùng khi đánh giá hệ thống (Chương 5).",
        );
      }
    } catch {
      toast.error("Không lưu được thay đổi", "Vui lòng thử lại.");
    } finally {
      setSaving(null);
    }
  }

  async function handleExport() {
    setExporting(true);
    try {
      const csv = await exportFeedbackCsv();
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "phan-hoi.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success("Đã xuất CSV", `Đã tải phan-hoi.csv (${stats.total} phản hồi).`);
    } catch {
      toast.error("Không xuất được CSV", "Vui lòng thử lại.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-h1 text-text-primary">Phản hồi</h1>
          <p className="mt-1 text-body-sm text-text-tertiary">
            Đánh giá Đúng/Sai của sinh viên cho từng câu trả lời, kèm các chunk đã được dùng.
          </p>
        </div>
        <Button
          variant="secondary"
          loading={exporting}
          icon={<Download size={16} aria-hidden="true" />}
          onClick={handleExport}
        >
          Xuất CSV
        </Button>
      </header>

      <section aria-label="Số liệu phản hồi" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Tổng phản hồi" value={stats.total} />
        <StatCard label="Đánh giá Đúng" value={stats.up_count} tone="navy" />
        <StatCard label="Đánh giá Sai" value={stats.down_count} tone="error" />
        <StatCard label="Sai · chưa xử lý" value={stats.unhandled_wrong_count} />
      </section>

      <div role="group" aria-label="Lọc phản hồi" className="inline-flex w-fit gap-1 rounded-md bg-bg-subtle p-1">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            aria-pressed={tab === t.value}
            onClick={() => setTab(t.value)}
            className={clsx(
              "h-control-sm cursor-pointer rounded-sm px-4 text-body-sm",
              tab === t.value
                ? "bg-bg-surface font-semibold text-text-primary shadow-sm"
                : "text-text-tertiary hover:text-text-primary",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {!loaded ? (
        <p role="status" className="text-body-sm text-text-muted">
          Đang tải phản hồi…
        </p>
      ) : items.length === 0 || !selected ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border-default bg-bg-surface px-6 py-12 text-center">
          <p className="text-body text-text-secondary">{EMPTY_MESSAGES[tab]}</p>
          {tab !== "all" ? (
            <Button variant="secondary" size="sm" onClick={() => setTab("all")}>
              Xem tất cả phản hồi
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <ul aria-label="Danh sách phản hồi" className="flex flex-col gap-2">
            {items.map((item) => {
              const active = item.feedback_id === selected.feedback_id;
              return (
                <li key={item.feedback_id}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => setSelectedId(item.feedback_id)}
                    className={clsx(
                      "w-full cursor-pointer rounded-lg border p-4 text-left transition-colors",
                      active
                        ? "border-brand-navy bg-info-bg"
                        : "border-border-default bg-bg-surface hover:bg-bg-hover",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <Badge tone={item.vote === "up" ? "success" : "error"} icon={false}>
                        {item.vote === "up" ? "Đúng" : "Sai"}
                      </Badge>
                      {item.handled ? (
                        <span className="flex items-center gap-1 text-caption-sm font-semibold text-success">
                          <Check size={12} aria-hidden="true" />
                          Đã xử lý
                        </span>
                      ) : null}
                      <span className="ml-auto text-caption-sm text-text-muted">
                        {formatFeedbackTime(item.created_at)}
                      </span>
                    </span>
                    <span className="mt-2 block text-label text-text-primary">{item.question}</span>
                    {item.vote === "down" ? (
                      <span className="mt-1 block text-caption text-text-muted">
                        Lý do: {reasonText(item)}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>

          <article
            aria-label="Chi tiết phản hồi"
            className="min-w-0 rounded-xl border border-border-default bg-bg-surface p-6"
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-text-muted">
              <Badge tone={selected.vote === "up" ? "success" : "error"} icon={false}>
                Sinh viên đánh giá: {selected.vote === "up" ? "Đúng" : "Sai"}
              </Badge>
              <span>{formatFeedbackTime(selected.created_at)}</span>
              <span aria-hidden="true">·</span>
              <span className="break-all font-mono">{selected.message_id}</span>
            </div>

            <h2 className="mt-4 text-overline uppercase text-text-label">Câu hỏi</h2>
            <p className="mt-1 text-h2 text-text-primary">{selected.question}</p>

            <h3 className="mt-5 text-overline uppercase text-text-label">Câu trả lời của trợ lý</h3>
            <p className="mt-2 whitespace-pre-line rounded-lg bg-bg-page p-4 text-body-sm text-text-secondary">
              {selected.answer || "—"}
            </p>

            {selected.vote === "down" ? (
              <div className="mt-4 rounded-lg border border-error-border bg-bg-error-soft p-4">
                <p className="text-label text-error-text">Lý do: {reasonText(selected)}</p>
                {selected.note ? (
                  <p className="mt-1 text-body-sm text-text-secondary">{selected.note}</p>
                ) : null}
              </div>
            ) : null}

            <h3 className="mt-5 text-overline uppercase text-text-label">Chunk đã dùng để trả lời</h3>
            {selected.chunks.length === 0 ? (
              <p className="mt-2 text-body-sm text-text-muted">Không có chunk nào được ghi nhận.</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-2">
                {selected.chunks.map((chunk) => (
                  <li key={`${chunk.doc_id}-${chunk.chunk_id}`}>
                    <Link
                      href={`/admin/documents/${encodeURIComponent(chunk.doc_id)}`}
                      className="flex items-center gap-3 rounded-lg border border-border-default px-4 py-3 transition-colors hover:bg-bg-hover"
                    >
                      <FileIcon size={18} aria-hidden="true" className="shrink-0 text-text-tertiary" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-body-sm font-semibold text-text-primary">
                          {chunk.doc_title}
                        </span>
                        <span className="block text-caption-sm text-text-muted">
                          <span className="font-mono">{chunk.chunk_id}</span> · Trang {chunk.page} ·
                          rerank {chunk.rerank_score.toFixed(2)}
                        </span>
                      </span>
                      <ChevronRight size={16} aria-hidden="true" className="shrink-0 text-text-muted" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-6 flex flex-wrap gap-3 border-t border-border-divider pt-5">
              {selected.vote === "down" ? (
                selected.handled ? (
                  <Button
                    variant="secondary"
                    loading={saving === "handled"}
                    disabled={saving !== null}
                    icon={<Check size={16} aria-hidden="true" />}
                    className="border-success bg-success-bg text-success hover:bg-success-bg"
                    onClick={() => toggleHandled(selected)}
                  >
                    Đã xử lý · bấm để mở lại
                  </Button>
                ) : (
                  <Button
                    loading={saving === "handled"}
                    disabled={saving !== null}
                    icon={<Check size={16} aria-hidden="true" />}
                    onClick={() => toggleHandled(selected)}
                  >
                    Đánh dấu đã xử lý
                  </Button>
                )
              ) : null}
              <Button
                variant="secondary"
                loading={saving === "test"}
                disabled={saving !== null}
                icon={<ClipboardCheck size={16} aria-hidden="true" />}
                onClick={() => toggleTestSet(selected)}
              >
                {selected.in_test_set ? "Đã có trong bộ test · bấm để bỏ" : "Thêm vào bộ test"}
              </Button>
              <Link
                href="/admin/documents"
                className="inline-flex h-control min-w-control items-center justify-center gap-2 rounded-md border border-border-strong bg-bg-surface px-4 text-label text-text-secondary transition-colors hover:bg-bg-hover"
              >
                <Upload size={16} aria-hidden="true" />
                Cập nhật tài liệu
              </Link>
            </div>
          </article>
        </div>
      )}
    </div>
  );
}

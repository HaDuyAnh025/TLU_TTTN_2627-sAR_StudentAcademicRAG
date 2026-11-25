import type { ConversationSummary } from "./types";

export type DateGroupId = "today" | "week" | "older";

export interface DateGroup<T> {
  id: DateGroupId;
  label: string;
  items: T[];
}

const GROUP_LABELS: Record<DateGroupId, string> = {
  today: "Hôm nay",
  week: "7 ngày trước",
  older: "Tháng trước",
};

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function getDateGroupId(iso: string, now: Date = new Date()): DateGroupId {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "older";
  const today = startOfDay(now);
  if (time >= today) return "today";
  if (time >= today - 7 * DAY_MS) return "week";
  return "older";
}

/** Nhóm lịch sử theo Hôm nay / 7 ngày trước / Tháng trước (bỏ nhóm rỗng). */
export function groupConversationsByDate(
  items: ReadonlyArray<ConversationSummary>,
  now: Date = new Date(),
): DateGroup<ConversationSummary>[] {
  const buckets: Record<DateGroupId, ConversationSummary[]> = {
    today: [],
    week: [],
    older: [],
  };
  const sorted = [...items].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
  for (const item of sorted) {
    buckets[getDateGroupId(item.updated_at, now)].push(item);
  }
  return (["today", "week", "older"] as const)
    .filter((id) => buckets[id].length > 0)
    .map((id) => ({ id, label: GROUP_LABELS[id], items: buckets[id] }));
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "Vừa xong" nếu dưới 10 phút, ngược lại dd/mm/yyyy. */
export function formatUpdatedAt(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  if (now.getTime() - date.getTime() < 10 * 60 * 1000) return "Vừa xong";
  return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** "18/11/2026 · 21:05" */
export function formatIndexedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "Hôm nay · 09:12" / "Hôm qua · 21:03" / "19/11 · 10:15" */
export function formatFeedbackTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const today = startOfDay(now);
  if (d.getTime() >= today) return `Hôm nay · ${time}`;
  if (d.getTime() >= today - DAY_MS) return `Hôm qua · ${time}`;
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} · ${time}`;
}

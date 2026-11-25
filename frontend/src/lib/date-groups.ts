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

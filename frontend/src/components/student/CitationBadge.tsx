import clsx from "clsx";

export interface CitationBadgeProps {
  n: number;
  /** Nguồn đang xem ở panel phải. */
  selected?: boolean;
  /** Không truyền → hiển thị tĩnh (ví dụ lúc câu trả lời đang hiện dần). */
  onSelect?: (n: number) => void;
  /** Tên nguồn, dùng cho nhãn trợ năng. */
  title?: string;
  className?: string;
}

const BASE =
  "mx-0.5 inline-flex size-6 items-center justify-center rounded-xs align-middle text-caption-sm font-semibold";

export function CitationBadge({ n, selected = false, onSelect, title, className }: CitationBadgeProps) {
  const tone = selected
    ? "bg-brand-navy text-text-on-brand"
    : "bg-brand-navy-soft text-brand-navy";

  if (!onSelect) {
    return <span className={clsx(BASE, tone, className)}>{n}</span>;
  }
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={title ? `Nguồn ${n}: ${title}` : `Nguồn ${n}`}
      onClick={() => onSelect(n)}
      className={clsx(BASE, tone, "cursor-pointer", className)}
    >
      {n}
    </button>
  );
}

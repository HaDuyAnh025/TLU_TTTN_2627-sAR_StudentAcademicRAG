import clsx from "clsx";
import { FileText, Globe } from "lucide-react";
import type { Citation } from "@/lib/types";

export function citationMeta(citation: Citation): string {
  if (citation.type === "web") {
    if (!citation.url) return "Trang web";
    try {
      return new URL(citation.url).hostname;
    } catch {
      return citation.url;
    }
  }
  const loc = citation.loc?.split("›").pop()?.trim();
  const page = citation.page !== undefined ? `Trang ${citation.page}` : undefined;
  return [loc, page].filter(Boolean).join(" · ") || "Tài liệu PDF";
}

export interface SourceCardProps {
  citation: Citation;
  selected: boolean;
  onSelect: (n: number) => void;
}

export function SourceCard({ citation, selected, onSelect }: SourceCardProps) {
  const MetaIcon = citation.type === "web" ? Globe : FileText;
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onSelect(citation.n)}
      className={clsx(
        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-left transition-colors",
        selected
          ? "border-brand-navy bg-brand-navy-soft"
          : "border-border-default bg-bg-surface hover:bg-bg-hover",
      )}
    >
      <span
        className={clsx(
          "flex size-6 shrink-0 items-center justify-center rounded-xs text-caption-sm font-semibold",
          selected ? "bg-brand-navy text-text-on-brand" : "bg-bg-subtle text-text-secondary",
        )}
      >
        {citation.n}
      </span>
      <span className="min-w-0">
        <span className="block text-body-sm font-semibold text-text-primary">{citation.title}</span>
        <span className="mt-1 flex items-center gap-1.5 text-caption-sm text-text-muted">
          <MetaIcon size={12} aria-hidden="true" className="shrink-0" />
          <span className="truncate">{citationMeta(citation)}</span>
        </span>
      </span>
    </button>
  );
}

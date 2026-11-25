import clsx from "clsx";
import type { ReactNode } from "react";

export type BadgeTone = "success" | "processing" | "error" | "neutral" | "file";

const TONES: Record<BadgeTone, string> = {
  success: "bg-success-bg text-success",
  processing: "bg-info-bg text-brand-navy",
  error: "bg-error-bg text-error-text",
  neutral: "bg-bg-subtle text-text-tertiary",
  file: "bg-bg-subtle text-text-tertiary",
};

export interface BadgeProps {
  tone?: BadgeTone;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = "neutral", icon, className, children }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 px-2.5 py-0.5 text-caption-sm font-semibold",
        tone === "file" ? "rounded-xs" : "rounded-full",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

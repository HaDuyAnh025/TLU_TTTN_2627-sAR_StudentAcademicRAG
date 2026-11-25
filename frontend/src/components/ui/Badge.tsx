import clsx from "clsx";
import { AlertCircle, Check, Loader2 } from "lucide-react";
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
  /**
   * Icon mặc định chỉ dành cho trạng thái xử lý tài liệu (Đã index / Đang xử lý / Lỗi).
   * Badge đánh giá Đúng/Sai của sinh viên luôn dùng icon={false}.
   */
  icon?: ReactNode | false;
  className?: string;
  children: ReactNode;
}

function defaultIcon(tone: BadgeTone): ReactNode {
  switch (tone) {
    case "success":
      return <Check size={12} aria-hidden="true" />;
    case "processing":
      return <Loader2 size={12} className="animate-spin" aria-hidden="true" />;
    case "error":
      return <AlertCircle size={12} aria-hidden="true" />;
    default:
      return null;
  }
}

export function Badge({ tone = "neutral", icon, className, children }: BadgeProps) {
  const resolvedIcon = icon === false ? null : (icon ?? defaultIcon(tone));
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 text-caption-sm font-semibold",
        tone === "file" ? "rounded-xs" : "rounded-full",
        TONES[tone],
        className,
      )}
    >
      {resolvedIcon}
      {children}
    </span>
  );
}

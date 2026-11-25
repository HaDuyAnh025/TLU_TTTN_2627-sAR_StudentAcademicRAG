import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface ChipProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-pressed"> {
  /** Trạng thái bật/tắt; luôn xuất ra aria-pressed. */
  pressed?: boolean;
  icon?: ReactNode;
  /** Bo tròn hoàn toàn (chip lý do báo Sai); mặc định bo 12px. */
  pill?: boolean;
}

export function Chip({
  pressed = false,
  icon,
  pill = false,
  className,
  children,
  type = "button",
  ...rest
}: ChipProps) {
  return (
    <button
      type={type}
      aria-pressed={pressed}
      className={clsx(
        "inline-flex min-h-control-sm cursor-pointer items-center gap-2 border px-3.5 text-body-sm transition-colors",
        pill ? "rounded-full" : "rounded-lg",
        pressed
          ? "border-brand-navy bg-brand-navy text-text-on-brand font-semibold"
          : "border-border-strong bg-bg-surface text-text-secondary hover:bg-bg-hover",
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

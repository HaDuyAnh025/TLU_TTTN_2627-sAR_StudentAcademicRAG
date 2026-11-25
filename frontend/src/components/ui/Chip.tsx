import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface ChipProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-pressed"> {
  /** Trạng thái bật/tắt; luôn xuất ra aria-pressed. */
  pressed?: boolean;
  icon?: ReactNode;
}

export function Chip({
  pressed = false,
  icon,
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
        "inline-flex min-h-control-sm cursor-pointer items-center gap-2 rounded-lg border px-3.5 text-body-sm transition-colors",
        pressed
          ? "border-brand-navy bg-brand-navy-soft font-semibold text-brand-navy"
          : "border-border-default bg-bg-surface text-text-secondary hover:bg-bg-hover",
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

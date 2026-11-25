import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger" | "danger-outline" | "ghost";
export type ButtonSize = "md" | "sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Nút chỉ có icon: bắt buộc truyền aria-label. */
  iconOnly?: boolean;
  /** Icon hiển thị trước nhãn. */
  icon?: ReactNode;
  loading?: boolean;
  fullWidth?: boolean;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand-navy text-text-on-brand border border-brand-navy hover:opacity-90",
  secondary:
    "bg-bg-surface text-text-secondary border border-border-strong hover:bg-bg-hover",
  danger: "bg-error text-text-on-brand border border-error hover:opacity-90",
  "danger-outline": "bg-bg-surface text-error-text border border-error hover:bg-error-bg",
  ghost: "bg-transparent text-brand-navy border border-transparent hover:bg-bg-hover",
};

const SIZES: Record<ButtonSize, string> = {
  md: "h-control min-w-control text-label",
  sm: "h-control-sm min-w-control-sm text-body-sm font-semibold",
};

export function Button({
  variant = "primary",
  size = "md",
  iconOnly = false,
  icon,
  loading = false,
  fullWidth = false,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "inline-flex cursor-pointer items-center justify-center gap-2 rounded-md transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        iconOnly ? "px-0" : "px-4",
        fullWidth && "w-full",
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}

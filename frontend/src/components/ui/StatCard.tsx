import clsx from "clsx";

export interface StatCardProps {
  label: string;
  value: number | string;
  tone?: "default" | "navy" | "error";
  className?: string;
}

const VALUE_TONES = {
  default: "text-text-primary",
  navy: "text-brand-navy",
  error: "text-error-text",
} as const;

export function StatCard({ label, value, tone = "default", className }: StatCardProps) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-border-default bg-bg-surface p-5",
        className,
      )}
    >
      <p className="text-caption text-text-muted">{label}</p>
      <p className={clsx("mt-1 text-stat", VALUE_TONES[tone])}>
        {typeof value === "number" ? value.toLocaleString("vi-VN") : value}
      </p>
    </div>
  );
}

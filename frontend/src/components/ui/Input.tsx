"use client";

import clsx from "clsx";
import { useId } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

interface FieldShellProps {
  id: string;
  label?: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}

function FieldShell({ id, label, error, hint, children }: FieldShellProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {label ? (
        <label htmlFor={id} className="text-label text-text-secondary">
          {label}
        </label>
      ) : null}
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className="text-caption text-text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-caption text-error-text">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function controlClass(invalid: boolean) {
  return clsx(
    "w-full rounded-md border bg-bg-surface px-3.5 text-body text-text-primary",
    "placeholder:text-text-muted disabled:cursor-not-allowed disabled:bg-bg-subtle",
    invalid ? "border-error" : "border-border-input",
  );
}

function describedBy(id: string, error?: string, hint?: string) {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  /** Viền đỏ + aria-invalid mà không hiện thông điệp riêng (lỗi đã nêu ở khối khác). */
  invalid?: boolean;
}

export function Input({ label, error, hint, invalid, id, className, ...rest }: InputProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell id={fieldId} label={label} error={error} hint={hint}>
      <input
        id={fieldId}
        aria-invalid={error || invalid ? true : undefined}
        aria-describedby={describedBy(fieldId, error, hint)}
        className={clsx(controlClass(Boolean(error) || Boolean(invalid)), "h-control", className)}
        {...rest}
      />
    </FieldShell>
  );
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export function Textarea({
  label,
  error,
  hint,
  id,
  className,
  rows = 3,
  ...rest
}: TextareaProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell id={fieldId} label={label} error={error} hint={hint}>
      <textarea
        id={fieldId}
        rows={rows}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, error, hint)}
        className={clsx(controlClass(Boolean(error)), "resize-y py-2.5", className)}
        {...rest}
      />
    </FieldShell>
  );
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export function Select({
  label,
  error,
  hint,
  id,
  className,
  children,
  ...rest
}: SelectProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell id={fieldId} label={label} error={error} hint={hint}>
      <select
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, error, hint)}
        className={clsx(controlClass(Boolean(error)), "h-control", className)}
        {...rest}
      >
        {children}
      </select>
    </FieldShell>
  );
}

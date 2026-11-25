"use client";

import clsx from "clsx";
import { Send } from "lucide-react";
import { useId } from "react";
import type { FormEvent, KeyboardEvent, Ref } from "react";
import { Button } from "@/components/ui/Button";

export interface QuestionComposerProps {
  value: string;
  onChange: (value: string) => void;
  /** Gọi khi người dùng gửi (nút hoặc Enter). Giá trị chưa được trim/validate. */
  onSubmit: () => void;
  /** Lỗi hiển thị ngay dưới ô nhập (role="alert"). */
  error?: string;
  disabled?: boolean;
  loading?: boolean;
  placeholder?: string;
  rows?: number;
  textareaRef?: Ref<HTMLTextAreaElement>;
  className?: string;
}

export function QuestionComposer({
  value,
  onChange,
  onSubmit,
  error,
  disabled = false,
  loading = false,
  placeholder = "Ví dụ: Điều kiện để được xét tốt nghiệp là gì?",
  rows = 2,
  textareaRef,
  className,
}: QuestionComposerProps) {
  const errorId = useId();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!disabled) onSubmit();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!disabled) onSubmit();
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className={className}>
      <div
        className={clsx(
          "flex items-end gap-3 rounded-ask border bg-bg-surface p-3 pl-5",
          "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-brand-navy",
          error ? "border-error" : "border-border-input",
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          rows={rows}
          disabled={disabled}
          placeholder={placeholder}
          aria-label="Câu hỏi của bạn"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          className="min-w-0 flex-1 resize-none self-stretch bg-transparent pt-1 text-body-lg text-text-primary outline-none placeholder:text-text-muted disabled:cursor-not-allowed"
        />
        <Button
          type="submit"
          iconOnly
          loading={loading}
          disabled={disabled}
          aria-label="Gửi câu hỏi"
          className="shrink-0"
        >
          <Send size={18} aria-hidden="true" />
        </Button>
      </div>
      {error ? (
        <p id={errorId} role="alert" className="mt-2 text-caption font-semibold text-error-text">
          {error}
        </p>
      ) : null}
    </form>
  );
}

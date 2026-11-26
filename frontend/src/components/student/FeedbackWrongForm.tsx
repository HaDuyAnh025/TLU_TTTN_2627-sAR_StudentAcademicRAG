"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Textarea } from "@/components/ui/Input";
import { FEEDBACK_REASONS } from "@/lib/constants";
import type { FeedbackReason } from "@/lib/types";

export interface WrongFormValue {
  reason: FeedbackReason;
  note?: string;
}

export interface FeedbackWrongFormProps {
  loading?: boolean;
  onCancel: () => void;
  onSubmit: (value: WrongFormValue) => void;
}

export function FeedbackWrongForm({ loading = false, onCancel, onSubmit }: FeedbackWrongFormProps) {
  const [reason, setReason] = useState<FeedbackReason | null>(null);
  const [note, setNote] = useState("");
  const [reasonError, setReasonError] = useState<string | undefined>();
  const [noteError, setNoteError] = useState<string | undefined>();

  const isOther = reason === "other";

  function handleSubmit() {
    if (!reason) {
      setReasonError("Vui lòng chọn một kiểu lỗi, hoặc chọn “Khác” để tự mô tả.");
      return;
    }
    const trimmed = note.trim();
    if (reason === "other" && !trimmed) {
      setNoteError("Bạn đã chọn “Khác”, vui lòng nhập mô tả lỗi.");
      return;
    }
    onSubmit({ reason, note: trimmed || undefined });
  }

  return (
    <div className="mt-4 rounded-lg border border-error-border bg-bg-error-soft p-4">
      <p className="text-label text-text-primary">
        Câu trả lời sai ở đâu? Chọn một kiểu lỗi hoặc tự mô tả.
      </p>
      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Kiểu lỗi">
        {FEEDBACK_REASONS.map((r) => (
          <Chip
            key={r.value}
            pressed={reason === r.value}
            pill
            onClick={() => {
              setReason(r.value);
              setReasonError(undefined);
              setNoteError(undefined);
            }}
          >
            {r.label}
          </Chip>
        ))}
      </div>
      {reasonError ? (
        <p role="alert" className="mt-2 text-caption font-semibold text-error-text">
          {reasonError}
        </p>
      ) : null}
      <div className="mt-4">
        <Textarea
          label={isOther ? "Mô tả lỗi (bắt buộc)" : "Mô tả thêm (không bắt buộc)"}
          placeholder="Mô tả cụ thể câu trả lời sai ở điểm nào…"
          value={note}
          error={noteError}
          errorIcon
          onChange={(e) => {
            setNote(e.target.value);
            if (noteError) setNoteError(undefined);
          }}
        />
      </div>
      <div className="mt-4 flex justify-end gap-3">
        <Button variant="secondary" size="sm" disabled={loading} onClick={onCancel}>
          Hủy
        </Button>
        <Button size="sm" loading={loading} onClick={handleSubmit}>
          Gửi phản hồi
        </Button>
      </div>
    </div>
  );
}

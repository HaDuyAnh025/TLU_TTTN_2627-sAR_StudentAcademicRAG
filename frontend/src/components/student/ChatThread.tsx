"use client";

import { AlertCircle, CornerDownRight, Loader2 } from "lucide-react";
import { AnswerCard } from "@/components/student/AnswerCard";
import { Button } from "@/components/ui/Button";
import { AnswerContent } from "@/lib/markdown";
import type { AnswerMessage } from "@/lib/types";

export interface PendingQuestion {
  question: string;
  status: "loading" | "streaming" | "error";
  /** Chữ đã hiện dần của câu trả lời đang soạn. */
  streamText: string;
}

export interface Selection {
  messageId: string;
  n: number;
}

export interface ChatThreadProps {
  messages: AnswerMessage[];
  pending: PendingQuestion | null;
  selection: Selection | null;
  onSelectCitation: (messageId: string, n: number) => void;
  onReplaceMessage: (oldId: string, next: AnswerMessage) => void;
  onRelatedClick: (question: string) => void;
  onRetry: () => void;
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="max-w-[80%] self-end whitespace-pre-line rounded-[16px_16px_4px_16px] bg-brand-navy px-5 py-3 text-body text-text-on-brand">
      {text}
    </div>
  );
}

function PendingAnswer({ pending, onRetry }: { pending: PendingQuestion; onRetry: () => void }) {
  if (pending.status === "error") {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center gap-3 rounded-lg border border-error-border bg-error-bg px-5 py-4"
      >
        <AlertCircle size={20} aria-hidden="true" className="shrink-0 text-error" />
        <p className="min-w-0 flex-1 text-body-sm text-text-primary">
          Không gửi được câu hỏi do mất kết nối tới máy chủ.
        </p>
        <Button size="sm" onClick={onRetry}>
          Thử lại
        </Button>
      </div>
    );
  }

  return (
    <article
      aria-busy="true"
      className="rounded-xl border border-border-default bg-bg-surface p-6"
    >
      <p role="status" className="flex items-center gap-2 text-body-sm text-text-muted">
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        {pending.status === "streaming"
          ? "Đang soạn câu trả lời…"
          : "Đang tìm trong tài liệu của trường và soạn câu trả lời…"}
      </p>
      {pending.streamText ? (
        <div className="mt-4">
          <AnswerContent text={pending.streamText} citations={[]} selectedN={null} />
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3" aria-hidden="true">
          <div className="h-4 w-full animate-pulse rounded-xs bg-bg-subtle" />
          <div className="h-4 w-11/12 animate-pulse rounded-xs bg-bg-subtle" />
          <div className="h-4 w-2/3 animate-pulse rounded-xs bg-bg-subtle" />
        </div>
      )}
    </article>
  );
}

export function ChatThread({
  messages,
  pending,
  selection,
  onSelectCitation,
  onReplaceMessage,
  onRelatedClick,
  onRetry,
}: ChatThreadProps) {
  return (
    <div className="flex flex-col gap-6">
      {messages.map((message) => (
        <div key={message.message_id} className="flex flex-col gap-6">
          <UserBubble text={message.question} />
          <AnswerCard
            message={message}
            selectedN={selection?.messageId === message.message_id ? selection.n : null}
            onSelectCitation={onSelectCitation}
            onReplaceMessage={onReplaceMessage}
          />
          {message.related_questions && message.related_questions.length > 0 ? (
            <section aria-label="Câu hỏi liên quan">
              <h3 className="mb-3 text-overline uppercase text-text-label">Câu hỏi liên quan</h3>
              <div className="flex flex-wrap gap-3">
                {message.related_questions.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => onRelatedClick(q)}
                    className="flex min-h-control cursor-pointer items-center gap-2.5 rounded-lg border border-border-default bg-bg-surface px-4 py-2 text-left text-body-sm text-text-secondary transition-colors hover:bg-bg-hover"
                  >
                    <CornerDownRight size={16} aria-hidden="true" className="shrink-0 text-text-muted" />
                    {q}
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      ))}

      {pending ? (
        <>
          <UserBubble text={pending.question} />
          <PendingAnswer pending={pending} onRetry={onRetry} />
        </>
      ) : null}
    </div>
  );
}

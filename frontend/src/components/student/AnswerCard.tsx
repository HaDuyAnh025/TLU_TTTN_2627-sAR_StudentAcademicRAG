"use client";

import clsx from "clsx";
import {
  BookOpen,
  Check,
  Copy,
  Loader2,
  RefreshCw,
  Search,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useState } from "react";
import { FeedbackWrongForm } from "@/components/student/FeedbackWrongForm";
import type { WrongFormValue } from "@/components/student/FeedbackWrongForm";
import { SourceCard } from "@/components/student/SourceCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { FEEDBACK_REASON_LABELS } from "@/lib/constants";
import { AnswerContent } from "@/lib/markdown";
import { getOrCreateSessionId } from "@/lib/storage";
import type { AnswerMessage, MessageFeedback } from "@/lib/types";
import { regenerate, sendFeedback } from "@/services/chat.service";

export interface AnswerCardProps {
  message: AnswerMessage;
  /** Số nguồn đang xem nếu nguồn đó thuộc câu trả lời này. */
  selectedN: number | null;
  onSelectCitation: (messageId: string, n: number) => void;
  /** Thay thế tin nhắn (sau khi đổi đánh giá hoặc tạo lại). */
  onReplaceMessage: (oldId: string, next: AnswerMessage) => void;
}

export function AnswerCard({
  message,
  selectedN,
  onSelectCitation,
  onReplaceMessage,
}: AnswerCardProps) {
  const toast = useToast();
  const [wrongFormOpen, setWrongFormOpen] = useState(false);
  const [changing, setChanging] = useState(false);
  const [sendingVote, setSendingVote] = useState<"up" | "down" | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  const hasSources = message.status === "ok" && message.citations.length > 0;
  const feedback = message.feedback;
  const showResult = Boolean(feedback) && !changing;

  async function submitFeedback(vote: "up" | "down", extra: Partial<WrongFormValue> = {}) {
    setSendingVote(vote);
    try {
      await sendFeedback({
        message_id: message.message_id,
        session_id: getOrCreateSessionId(),
        vote,
        reason: extra.reason,
        note: extra.note,
      });
      const next: MessageFeedback = { vote, reason: extra.reason, note: extra.note };
      onReplaceMessage(message.message_id, { ...message, feedback: next });
      setWrongFormOpen(false);
      setChanging(false);
      if (vote === "up") {
        toast.success("Cảm ơn bạn!", "Đã ghi nhận: câu trả lời này đúng.");
      } else {
        toast.success(
          "Đã gửi phản hồi",
          "Cảm ơn bạn! Phản hồi sẽ được dùng để cải thiện câu trả lời.",
        );
      }
    } catch {
      toast.error("Không gửi được phản hồi", "Mất kết nối tới máy chủ. Vui lòng thử lại.");
    } finally {
      setSendingVote(null);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(message.answer);
      toast.success("Đã sao chép", "Nội dung câu trả lời đã nằm trong bộ nhớ tạm.");
    } catch {
      toast.error("Không sao chép được", "Trình duyệt không cho phép truy cập bộ nhớ tạm.");
    }
  }

  async function handleRegenerate() {
    setRegenerating(true);
    setWrongFormOpen(false);
    try {
      const fresh = await regenerate(message.message_id, getOrCreateSessionId());
      onReplaceMessage(message.message_id, fresh);
      toast.success("Đã tạo lại câu trả lời", "Nội dung mới đã thay thế câu trả lời trước.");
    } catch {
      setRegenerating(false);
      toast.error("Không tạo lại được", "Mất kết nối tới máy chủ. Vui lòng thử lại.");
    }
    // Khi thành công, thẻ được thay bằng tin nhắn mới nên không cần tắt cờ.
  }

  if (message.status === "no_source") {
    return (
      <article className="rounded-xl border border-border-default bg-bg-surface p-6">
        <Badge tone="processing" icon={<Search size={12} aria-hidden="true" />}>
          Không tìm thấy nguồn phù hợp
        </Badge>
        <p className="mt-3 text-body-lg text-text-primary">{message.answer}</p>
      </article>
    );
  }

  const voteDisabled = sendingVote !== null || regenerating;

  return (
    <article
      aria-busy={regenerating || undefined}
      className="rounded-xl border border-border-default bg-bg-surface p-6"
    >
      <header className="flex items-center gap-3">
        <span className="flex size-8 items-center justify-center rounded-sm bg-info-bg text-brand-navy">
          <BookOpen size={18} aria-hidden="true" />
        </span>
        <p className="text-label text-text-primary">Trợ lý Học vụ</p>
        {regenerating ? (
          <span role="status" className="ml-auto flex items-center gap-2 text-caption text-text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            Đang tạo lại câu trả lời…
          </span>
        ) : null}
      </header>

      <div className={clsx("mt-4 transition-opacity", regenerating && "opacity-45")}>
        <AnswerContent
          text={message.answer}
          citations={message.citations}
          selectedN={selectedN}
          onSelectCitation={(n) => onSelectCitation(message.message_id, n)}
        />

        {hasSources ? (
          <section className="mt-5 border-t border-border-divider pt-4">
            <h3 className="text-overline uppercase text-text-label">
              Nguồn trích dẫn ({message.citations.length}) · Bấm để xem đoạn trích
            </h3>
            <div className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
              {message.citations.map((c) => (
                <SourceCard
                  key={c.chunk_id}
                  citation={c}
                  selected={selectedN === c.n}
                  onSelect={(n) => onSelectCitation(message.message_id, n)}
                />
              ))}
            </div>
          </section>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border-divider pt-4">
        {showResult && feedback ? (
          <>
            <p
              className={clsx(
                "flex items-center gap-2 text-label",
                feedback.vote === "up" ? "text-success" : "text-error-text",
              )}
            >
              <Check size={16} aria-hidden="true" />
              {feedback.vote === "up"
                ? "Bạn đã đánh giá: câu trả lời đúng"
                : `Đã gửi báo sai: ${
                    feedback.reason ? FEEDBACK_REASON_LABELS[feedback.reason] : "Khác"
                  }`}
            </p>
            <button
              type="button"
              disabled={voteDisabled}
              onClick={() => setChanging(true)}
              className="cursor-pointer text-body-sm font-medium text-brand-navy underline disabled:opacity-50"
            >
              Đổi đánh giá
            </button>
          </>
        ) : (
          <>
            <p className="text-label text-text-primary">Câu trả lời này có đúng không?</p>
            <Button
              variant="secondary"
              size="sm"
              icon={<ThumbsUp size={16} aria-hidden="true" />}
              loading={sendingVote === "up"}
              disabled={voteDisabled}
              onClick={() => submitFeedback("up")}
            >
              Đúng
            </Button>
            <Button
              variant="secondary"
              size="sm"
              aria-expanded={wrongFormOpen}
              icon={<ThumbsDown size={16} aria-hidden="true" />}
              disabled={voteDisabled}
              className={clsx(
                wrongFormOpen && "border-error bg-error-bg text-error-text hover:bg-error-bg",
              )}
              onClick={() => setWrongFormOpen((open) => !open)}
            >
              Sai
            </Button>
          </>
        )}
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            icon={<Copy size={16} aria-hidden="true" />}
            className="text-text-secondary"
            onClick={handleCopy}
          >
            Sao chép
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw size={16} aria-hidden="true" />}
            loading={regenerating}
            disabled={sendingVote !== null}
            className="text-text-secondary"
            onClick={handleRegenerate}
          >
            Tạo lại
          </Button>
        </div>
      </div>

      {wrongFormOpen && !showResult ? (
        <FeedbackWrongForm
          loading={sendingVote === "down"}
          onCancel={() => setWrongFormOpen(false)}
          onSubmit={(value) => submitFeedback("down", value)}
        />
      ) : null}
    </article>
  );
}

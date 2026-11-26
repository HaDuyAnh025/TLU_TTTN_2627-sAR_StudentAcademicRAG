"use client";

import {
  Calendar,
  Clipboard,
  CornerDownRight,
  CreditCard,
  FileText,
  GraduationCap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { QuestionComposer } from "@/components/student/QuestionComposer";
import { useToast } from "@/components/ui/Toast";
import { SUGGESTED_QUESTION_GROUPS } from "@/lib/constants";
import type { SuggestedGroupIcon } from "@/lib/constants";
import { getOrCreateSessionId } from "@/lib/storage";
import { createConversation } from "@/services/chat.service";

const GROUP_ICONS: Record<SuggestedGroupIcon, LucideIcon> = {
  "graduation-cap": GraduationCap,
  "credit-card": CreditCard,
  calendar: Calendar,
  clipboard: Clipboard,
};

const EMPTY_QUESTION_ERROR =
  "Bạn chưa nhập câu hỏi. Hãy gõ câu hỏi hoặc chọn một gợi ý bên dưới.";

export function WelcomeView() {
  const router = useRouter();
  const toast = useToast();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  async function start(text: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      setError(EMPTY_QUESTION_ERROR);
      textareaRef.current?.focus();
      return;
    }
    setError(undefined);
    setBusy(true);
    try {
      const conversation = await createConversation(trimmed, getOrCreateSessionId());
      router.push(`/c/${conversation.conversation_id}`);
    } catch {
      setBusy(false);
      toast.error("Không bắt đầu được cuộc trò chuyện", "Vui lòng thử lại.");
    }
  }

  return (
    <div className="mx-auto w-full max-w-welcome px-6 pb-12 pt-10 lg:px-0 lg:pt-14">
      <header className="text-center">
        <h1 className="text-display text-text-primary">Bạn cần tra cứu thông tin học vụ gì?</h1>
        <p className="mx-auto mt-3 max-w-[620px] text-body-lg text-text-tertiary">
          Hỏi bằng tiếng Việt tự nhiên. Mỗi câu trả lời đều kèm nguồn trích dẫn — tên văn bản,
          trang hoặc đường link — để bạn tự kiểm tra lại.
        </p>
      </header>

      <QuestionComposer
        className="mt-8"
        value={question}
        onChange={(v) => {
          setQuestion(v);
          if (error) setError(undefined);
        }}
        onSubmit={() => start(question)}
        error={error}
        loading={busy}
        disabled={busy}
        textareaRef={textareaRef}
      />

      <h2 className="mb-4 mt-8 text-overline uppercase text-text-label">Gợi ý câu hỏi</h2>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(300px,100%),1fr))] gap-4">
        {SUGGESTED_QUESTION_GROUPS.map((group) => {
          const Icon = GROUP_ICONS[group.icon];
          return (
            <section
              key={group.id}
              aria-labelledby={`group-${group.id}`}
              className="rounded-lg border border-border-default bg-bg-surface p-4"
            >
              <div className="flex items-center gap-3 px-2 py-2">
                <span className="flex size-8 items-center justify-center rounded-sm bg-brand-navy-soft text-brand-navy">
                  <Icon size={16} aria-hidden="true" />
                </span>
                <h3 id={`group-${group.id}`} className="text-h3 text-text-primary">
                  {group.title}
                </h3>
              </div>
              <ul className="mt-1 flex flex-col">
                {group.questions.map((q) => (
                  <li key={q}>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => start(q)}
                      className="flex min-h-control w-full cursor-pointer items-center gap-3 rounded-sm px-2 py-2 text-left text-body-sm text-text-secondary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <CornerDownRight
                        size={16}
                        aria-hidden="true"
                        className="shrink-0 text-text-muted"
                      />
                      <span>{q}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>

      <p className="mt-8 flex items-center justify-center gap-2 text-center text-caption text-text-muted">
        <FileText size={14} aria-hidden="true" className="shrink-0" />
        Dữ liệu tra cứu: quy chế, quy định và thông báo đăng trên thanglong.edu.vn
      </p>
    </div>
  );
}

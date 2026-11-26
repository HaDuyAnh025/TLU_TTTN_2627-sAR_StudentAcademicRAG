"use client";

import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatThread } from "@/components/student/ChatThread";
import type { PendingQuestion, Selection } from "@/components/student/ChatThread";
import { QuestionComposer } from "@/components/student/QuestionComposer";
import { SourcePanel } from "@/components/student/SourcePanel";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { getOrCreateSessionId } from "@/lib/storage";
import type { AnswerMessage } from "@/lib/types";
import { chatStream, deleteConversation, getConversation } from "@/services/chat.service";

type LoadState = "loading" | "ready" | "not_found";

function firstSelection(message: AnswerMessage | undefined): Selection | null {
  if (!message || message.status !== "ok" || message.citations.length === 0) return null;
  return { messageId: message.message_id, n: message.citations[0].n };
}

export function ConversationView({ conversationId }: { conversationId: string }) {
  const router = useRouter();
  const toast = useToast();

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [title, setTitle] = useState("");
  const [messages, setMessages] = useState<AnswerMessage[]>([]);
  const [pending, setPending] = useState<PendingQuestion | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [input, setInput] = useState("");
  const [inputError, setInputError] = useState<string | undefined>();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrolledOnce = useRef(false);

  const send = useCallback(
    async (question: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setPending({ question, status: "loading", streamText: "" });
      try {
        const message = await chatStream(
          { session_id: getOrCreateSessionId(), conversation_id: conversationId, question },
          {
            signal: controller.signal,
            onDelta: (text) =>
              setPending((p) =>
                p ? { ...p, status: "streaming", streamText: p.streamText + text } : p,
              ),
          },
        );
        setMessages((prev) => [...prev, message]);
        setPending(null);
        const next = firstSelection(message);
        if (next) setSelection(next);
      } catch (error) {
        if (controller.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }
        setPending({ question, status: "error", streamText: "" });
        toast.error(
          "Không gửi được câu hỏi",
          "Mất kết nối tới máy chủ. Bấm “Thử lại” trong khung chat.",
        );
      }
    },
    [conversationId, toast],
  );

  // Tải hội thoại; nếu còn câu hỏi chờ (từ màn 1) thì tự gửi.
  useEffect(() => {
    let cancelled = false;
    getConversation(conversationId, getOrCreateSessionId()).then((conversation) => {
      if (cancelled) return;
      if (!conversation) {
        setLoadState("not_found");
        return;
      }
      setTitle(conversation.title);
      setMessages(conversation.messages);
      setSelection(firstSelection([...conversation.messages].reverse().find(
        (m) => m.status === "ok" && m.citations.length > 0,
      )));
      setLoadState("ready");
      if (conversation.pending_question) void send(conversation.pending_question);
    });
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [conversationId, send]);

  // Cuộn xuống cuối khi có tin nhắn / trạng thái mới (không cuộn ở lần hiển thị đầu).
  const streamLength = pending?.streamText.length ?? 0;
  useEffect(() => {
    if (loadState !== "ready") return;
    if (!scrolledOnce.current) {
      scrolledOnce.current = true;
      return;
    }
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [loadState, messages.length, pending?.status, streamLength]);

  const handleSelectCitation = useCallback((messageId: string, n: number) => {
    setSelection({ messageId, n });
  }, []);

  const handleReplaceMessage = useCallback((oldId: string, next: AnswerMessage) => {
    setMessages((prev) => prev.map((m) => (m.message_id === oldId ? next : m)));
    if (next.message_id !== oldId) {
      setSelection((sel) => (sel?.messageId === oldId ? firstSelection(next) : sel));
    }
  }, []);

  function handleSubmit() {
    const question = input.trim();
    if (!question) {
      setInputError("Bạn chưa nhập câu hỏi. Hãy gõ câu hỏi trước khi gửi.");
      textareaRef.current?.focus();
      return;
    }
    setInputError(undefined);
    setInput("");
    void send(question);
  }

  function handleRelatedClick(question: string) {
    setInput(question);
    setInputError(undefined);
    textareaRef.current?.focus();
    toast.info("Đã điền câu hỏi gợi ý", "Bấm nút gửi để hỏi tiếp trong cuộc trò chuyện này.");
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteConversation(conversationId);
      setDeleteOpen(false);
      toast.success("Đã xóa hội thoại", `“${title}” đã được xóa khỏi lịch sử.`);
      router.push("/");
    } catch {
      toast.error("Không xóa được hội thoại", "Vui lòng thử lại.");
      setDeleting(false);
    }
  }

  const selectedCitation = useMemo(() => {
    if (!selection) return null;
    const message = messages.find((m) => m.message_id === selection.messageId);
    const citation = message?.citations.find((c) => c.n === selection.n) ?? null;
    return citation && message ? { citation, total: message.citations.length } : null;
  }, [messages, selection]);

  const latestSourceCount = useMemo(() => {
    const latest = [...messages].reverse().find((m) => m.status === "ok" && m.citations.length > 0);
    return latest?.citations.length ?? 0;
  }, [messages]);

  if (loadState === "loading") {
    return (
      <div role="status" className="px-6 py-14 text-body text-text-muted">
        Đang tải cuộc trò chuyện…
      </div>
    );
  }

  if (loadState === "not_found") {
    return (
      <div className="mx-auto flex w-full max-w-chat flex-col items-start gap-4 px-6 py-14">
        <h1 className="text-h1 text-text-primary">Không tìm thấy cuộc trò chuyện</h1>
        <p className="text-body text-text-secondary">
          Cuộc trò chuyện này không còn trong lịch sử của trình duyệt (có thể đã bị xóa).
        </p>
        <Link
          href="/"
          className="inline-flex h-control items-center rounded-md border border-brand-navy bg-brand-navy px-4 text-label text-text-on-brand hover:opacity-90"
        >
          Bắt đầu cuộc trò chuyện mới
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col xl:h-screen xl:flex-row">
      <section aria-label="Cuộc trò chuyện" className="flex min-w-0 flex-1 flex-col xl:h-screen">
        <header className="flex items-center justify-between gap-4 border-b border-border-default bg-bg-surface px-6 py-4 lg:px-8">
          <div className="min-w-0">
            <h1 className="truncate text-h2 text-text-primary">{title}</h1>
            <p className="truncate text-caption text-text-muted">
              {latestSourceCount > 0
                ? `Câu trả lời dựa trên ${latestSourceCount} nguồn từ văn bản của trường`
                : "Câu trả lời luôn kèm nguồn trích dẫn từ văn bản của trường"}
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            className="shrink-0"
            icon={<Trash2 size={16} aria-hidden="true" />}
            onClick={() => setDeleteOpen(true)}
          >
            Xóa hội thoại
          </Button>
        </header>

        <div className="px-6 py-6 xl:min-h-0 xl:flex-1 xl:overflow-y-auto">
          <div className="mx-auto w-full max-w-chat">
            <ChatThread
              messages={messages}
              pending={pending}
              selection={selection}
              onSelectCitation={handleSelectCitation}
              onReplaceMessage={handleReplaceMessage}
              onRelatedClick={handleRelatedClick}
              onRetry={() => pending && void send(pending.question)}
            />
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="px-6 pb-4 pt-2">
          <div className="mx-auto w-full max-w-chat">
            <QuestionComposer
              value={input}
              onChange={(v) => {
                setInput(v);
                if (inputError) setInputError(undefined);
              }}
              onSubmit={handleSubmit}
              error={inputError}
              disabled={pending !== null && pending.status !== "error"}
              placeholder="Hỏi về quy chế, học phí, học bổng, đăng ký học phần…"
              textareaRef={textareaRef}
            />
            <p className="mt-2 text-center text-caption-sm text-text-muted">
              Câu trả lời được tạo từ văn bản chính thức của trường. Hãy kiểm tra nguồn trích dẫn
              trước khi làm thủ tục.
            </p>
          </div>
        </div>
      </section>

      <SourcePanel
        citation={selectedCitation?.citation ?? null}
        total={selectedCitation?.total ?? 0}
      />

      <Dialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Xóa cuộc trò chuyện này?"
        description={`“${title}” sẽ bị xóa khỏi lịch sử. Bạn sẽ được đưa về màn hình bắt đầu.`}
        footer={
          <>
            <Button variant="secondary" disabled={deleting} onClick={() => setDeleteOpen(false)}>
              Hủy
            </Button>
            <Button variant="danger" loading={deleting} onClick={handleDelete}>
              Xóa hội thoại
            </Button>
          </>
        }
      />
    </div>
  );
}

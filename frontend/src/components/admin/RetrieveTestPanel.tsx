"use client";

import { AlertCircle, Play } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import type { RetrieveTestHit } from "@/lib/types";
import { retrieveTest } from "@/services/admin.service";

export interface RetrieveTestPanelProps {
  docId: string;
}

export function RetrieveTestPanel({ docId }: RetrieveTestPanelProps) {
  const toast = useToast();
  const [question, setQuestion] = useState("");
  const [onlyThisDoc, setOnlyThisDoc] = useState(true);
  const [questionError, setQuestionError] = useState<string | undefined>();
  const [running, setRunning] = useState(false);
  const [hits, setHits] = useState<RetrieveTestHit[] | null>(null);
  const [failure, setFailure] = useState<string | undefined>();

  async function handleRun() {
    if (question.trim() === "") {
      setQuestionError("Vui lòng nhập câu hỏi để thử truy xuất.");
      return;
    }
    setQuestionError(undefined);
    setFailure(undefined);
    setRunning(true);
    try {
      const res = await retrieveTest({
        question: question.trim(),
        doc_id: onlyThisDoc ? docId : undefined,
      });
      setHits(res.items);
      toast.info(
        "Đã chạy thử truy xuất",
        res.items.length > 0
          ? `Tìm thấy ${res.items.length} chunk liên quan nhất.`
          : "Không tìm thấy chunk phù hợp.",
      );
    } catch (error) {
      setHits(null);
      const message =
        error instanceof Error ? error.message : "Không kết nối được tới Qdrant. Vui lòng thử lại.";
      setFailure(message);
      toast.error("Thử truy xuất thất bại", "Không kết nối được tới Qdrant.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <aside
      aria-labelledby="retrieve-title"
      className="rounded-xl border border-border-default bg-bg-surface p-6"
    >
      <h2 id="retrieve-title" className="text-h2 text-text-primary">
        Thử truy xuất
      </h2>
      <p className="mt-1 text-body-sm text-text-tertiary">
        Nhập một câu hỏi để xem chunk nào được tìm thấy và xếp hạng lại.
      </p>

      <div className="mt-4">
        <Textarea
          aria-label="Câu hỏi thử truy xuất"
          rows={2}
          placeholder="Ví dụ: Điều kiện để được xét tốt nghiệp là gì?"
          value={question}
          error={questionError}
          onChange={(e) => {
            setQuestion(e.target.value);
            if (questionError) setQuestionError(undefined);
          }}
        />
      </div>

      <label className="mt-3 flex cursor-pointer items-center gap-3 text-body-sm text-text-secondary">
        <input
          type="checkbox"
          checked={onlyThisDoc}
          onChange={(e) => setOnlyThisDoc(e.target.checked)}
          className="size-4 cursor-pointer accent-brand-navy"
        />
        Chỉ tìm trong tài liệu này
      </label>

      <Button
        fullWidth
        className="mt-4"
        loading={running}
        icon={<Play size={16} aria-hidden="true" />}
        onClick={handleRun}
      >
        {running ? "Đang chạy thử…" : "Chạy thử"}
      </Button>

      {failure ? (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-lg border border-error-border bg-error-bg px-4 py-3 text-body-sm text-error-text"
        >
          <AlertCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
          {failure}
        </div>
      ) : null}

      {hits ? (
        hits.length === 0 ? (
          <p className="mt-4 text-body-sm text-text-muted">Không tìm thấy chunk phù hợp.</p>
        ) : (
          <ol aria-label="Kết quả truy xuất" className="mt-4 flex flex-col gap-3">
            {hits.map((hit) => (
              <li key={`${hit.doc_id}-${hit.chunk_id}`} className="rounded-lg bg-bg-page p-3">
                <div className="flex items-start gap-3">
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-navy text-caption-sm font-semibold text-text-on-brand">
                    {hit.rank}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-caption text-text-muted">
                      <span className="font-mono text-body-sm font-bold text-text-primary">
                        {hit.chunk_id}
                      </span>{" "}
                      · Trang {hit.page}
                      {!onlyThisDoc && hit.doc_title ? ` · ${hit.doc_title}` : ""}
                    </p>
                    <p className="mt-1 whitespace-pre-line text-body-sm text-text-secondary">
                      {hit.excerpt}
                    </p>
                    <div className="mt-2 flex items-center gap-3 text-caption text-text-muted">
                      <span>Rerank</span>
                      <div
                        role="meter"
                        aria-label="Điểm rerank"
                        aria-valuemin={0}
                        aria-valuemax={1}
                        aria-valuenow={hit.rerank_score}
                        className="h-1.5 flex-1 overflow-hidden rounded-full bg-border-default"
                      >
                        <div
                          className="h-full rounded-full bg-brand-navy"
                          style={{ width: `${Math.round(hit.rerank_score * 100)}%` }}
                        />
                      </div>
                      <span className="font-semibold tabular-nums text-text-primary">
                        {hit.rerank_score.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )
      ) : null}

      <p className="mt-4 text-caption text-text-muted">
        Lấy top-10 từ Qdrant, rerank bằng bge-reranker-v2-m3, giữ lại 3 chunk đầu để đưa vào LLM.
      </p>
    </aside>
  );
}

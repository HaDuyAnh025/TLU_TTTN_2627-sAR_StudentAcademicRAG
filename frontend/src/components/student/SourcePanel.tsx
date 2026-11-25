"use client";

import { ExternalLink, File as FileIcon, FileText, Globe, MousePointerClick } from "lucide-react";
import { useState } from "react";
import { PdfViewerDialog } from "@/components/student/PdfViewerDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { Citation } from "@/lib/types";

export interface SourcePanelProps {
  citation: Citation | null;
  total: number;
}

const PANEL_CLASS =
  "w-full border-t border-border-default bg-bg-surface p-6 lg:h-screen lg:w-source-panel lg:shrink-0 lg:overflow-y-auto lg:border-l lg:border-t-0";

export function SourcePanel({ citation, total }: SourcePanelProps) {
  const [pdfOpen, setPdfOpen] = useState(false);

  if (!citation) {
    return (
      <aside aria-label="Nguồn trích dẫn" className={PANEL_CLASS}>
        <p className="text-overline uppercase text-text-label">Nguồn trích dẫn</p>
        <div className="mt-4 flex flex-col items-center gap-3 rounded-lg border border-dashed border-border-strong px-4 py-8 text-center">
          <MousePointerClick size={22} aria-hidden="true" className="text-text-muted" />
          <p className="text-body-sm text-text-muted">
            Chọn một số trích dẫn hoặc thẻ nguồn trong câu trả lời để xem đoạn văn gốc tại đây.
          </p>
        </div>
      </aside>
    );
  }

  const isPdf = citation.type === "pdf";
  const SourceIcon = isPdf ? FileText : Globe;
  const sourceLabel = isPdf ? citation.file : citation.url;

  return (
    <aside aria-label="Nguồn trích dẫn" className={PANEL_CLASS}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-overline uppercase text-text-label">
          Nguồn {citation.n} / {total}
        </p>
        <Badge tone="file">{isPdf ? "PDF" : "Trang web"}</Badge>
      </div>
      <h2 className="mt-3 text-h2 text-text-primary">{citation.title}</h2>
      {sourceLabel ? (
        <p className="mt-2 flex items-start gap-1.5 break-all text-caption text-text-muted">
          <SourceIcon size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
          {sourceLabel}
        </p>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-4 rounded-lg bg-bg-page p-4">
        <div>
          <dt className="text-caption-sm text-text-muted">Vị trí</dt>
          <dd className="mt-0.5 text-body-sm font-semibold text-text-primary">
            {citation.loc ?? (isPdf ? "—" : "Trang web")}
          </dd>
        </div>
        <div>
          <dt className="text-caption-sm text-text-muted">Trang</dt>
          <dd className="mt-0.5 text-body-sm font-semibold text-text-primary">
            {citation.page ?? "—"}
          </dd>
        </div>
      </dl>

      <h3 className="mt-6 text-caption font-semibold text-text-secondary">
        Đoạn trích được dùng để trả lời
      </h3>
      <blockquote className="mt-2 rounded-lg border border-border-default bg-bg-surface p-4 text-body-sm leading-[1.7] text-text-secondary">
        {citation.excerpt_before}
        <mark className="rounded-xs bg-bg-highlight text-inherit">{citation.excerpt_highlight}</mark>
        {citation.excerpt_after}
      </blockquote>

      <div className="mt-4">
        {isPdf ? (
          <>
            <Button
              icon={<FileIcon size={16} aria-hidden="true" />}
              onClick={() => setPdfOpen(true)}
            >
              Xem PDF tại trang {citation.page ?? "—"}
            </Button>
            <PdfViewerDialog open={pdfOpen} onOpenChange={setPdfOpen} citation={citation} />
          </>
        ) : (
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-control min-w-control items-center justify-center gap-2 rounded-md border border-brand-navy bg-brand-navy px-4 text-label text-text-on-brand transition-colors hover:opacity-90"
          >
            <ExternalLink size={16} aria-hidden="true" />
            Mở trang web (tab mới)
          </a>
        )}
      </div>

      <p className="mt-6 text-caption text-text-muted">
        Đoạn văn này được hệ thống truy xuất từ kho tài liệu và xếp hạng lại là liên quan nhất tới
        câu hỏi. Phần tô màu là nội dung trợ lý đã dùng.
      </p>
    </aside>
  );
}

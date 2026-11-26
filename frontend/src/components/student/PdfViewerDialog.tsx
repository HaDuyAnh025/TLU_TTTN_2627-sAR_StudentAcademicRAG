"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { Download, File as FileIcon, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import type { Citation } from "@/lib/types";
import { useReturnFocus } from "@/lib/use-return-focus";
import { USE_MOCK } from "@/services/api";
import { fileUrl } from "@/services/chat.service";

export interface PdfViewerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  citation: Citation;
}

/** Xem nội dung text của trang PDF có đoạn trích được tô sáng (chưa dùng pdf.js/iframe). */
export function PdfViewerDialog({ open, onOpenChange, citation }: PdfViewerDialogProps) {
  const toast = useToast();
  const { onOpenAutoFocus, onCloseAutoFocus } = useReturnFocus();
  const page = citation.page ?? "—";
  const fileName = citation.file ?? citation.title;

  function handleDownload() {
    if (USE_MOCK) {
      toast.info(
        "Đang ở chế độ dữ liệu mẫu",
        "Chưa có file PDF thật. Khi nối backend, nút này tải file từ /api/files/{doc_id}.",
      );
      return;
    }
    window.open(fileUrl(citation.doc_id, citation.page), "_blank", "noopener,noreferrer");
    toast.success("Đang tải PDF", `${fileName} · Trang ${page}`);
  }

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <RadixDialog.Content
          onOpenAutoFocus={onOpenAutoFocus}
          onCloseAutoFocus={onCloseAutoFocus}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100vh-32px)] w-[calc(100vw-32px)] max-w-[760px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl bg-bg-surface shadow-dialog">
          <header className="flex items-center gap-3 px-5 py-4">
            <FileIcon size={22} aria-hidden="true" className="shrink-0 text-text-tertiary" />
            <div className="min-w-0 flex-1">
              <RadixDialog.Title className="truncate text-h3 text-text-primary">
                {citation.title}
              </RadixDialog.Title>
              <RadixDialog.Description className="truncate text-caption-sm text-text-muted">
                {fileName} · Trang {page}
              </RadixDialog.Description>
            </div>
            <RadixDialog.Close asChild>
              <Button variant="ghost" iconOnly aria-label="Đóng" className="text-text-secondary">
                <X size={18} aria-hidden="true" />
              </Button>
            </RadixDialog.Close>
          </header>

          <div className="overflow-y-auto bg-bg-pdf-viewer px-6 py-6">
            <div className="mx-auto max-w-[560px] bg-white px-11 py-12 shadow-dialog">
              <p className="text-center font-serif text-caption text-text-muted">— Trang {page} —</p>
              <p className="mt-6 whitespace-pre-line font-serif text-body-lg leading-[1.6] text-text-primary">
                {citation.excerpt_before}
                <mark className="rounded-xs bg-bg-highlight text-inherit">
                  {citation.excerpt_highlight}
                </mark>
                {citation.excerpt_after}
              </p>
            </div>
          </div>

          <footer className="flex justify-end gap-3 px-5 py-4">
            <Button
              variant="secondary"
              icon={<Download size={16} aria-hidden="true" />}
              onClick={handleDownload}
            >
              Tải PDF
            </Button>
            <RadixDialog.Close asChild>
              <Button>Đóng</Button>
            </RadixDialog.Close>
          </footer>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

"use client";

import { Download, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChunkListPanel } from "@/components/admin/ChunkListPanel";
import { RetrieveTestPanel } from "@/components/admin/RetrieveTestPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { INDEX_STEP_SHORT_LABELS, getDocCategoryLabel } from "@/lib/constants";
import { formatIndexedAt } from "@/lib/date-groups";
import type { DocumentDetail } from "@/lib/types";
import { USE_MOCK } from "@/services/api";
import {
  deleteDocument,
  getDocument,
  reindexDocument,
  subscribeAdminData,
} from "@/services/admin.service";
import { fileUrl } from "@/services/chat.service";

type LoadState = "loading" | "ready" | "not_found";

function InfoCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 px-5 py-4">
      <dt className="text-caption text-text-muted">{label}</dt>
      <dd className="mt-1 text-body font-semibold text-text-primary">{children}</dd>
    </div>
  );
}

export function DocumentDetailView({ docId }: { docId: string }) {
  const router = useRouter();
  const toast = useToast();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [reindexOpen, setReindexOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  // Tải chi tiết và cập nhật trực tiếp khi tiến trình re-index thay đổi.
  useEffect(() => {
    let cancelled = false;
    function load() {
      getDocument(docId).then((detail) => {
        if (cancelled) return;
        if (!detail) {
          setLoadState("not_found");
          return;
        }
        setDoc(detail);
        setLoadState("ready");
      });
    }
    load();
    const unsubscribe = subscribeAdminData(load);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [docId]);

  if (loadState === "loading") {
    return (
      <p role="status" className="text-body text-text-muted">
        Đang tải thông tin tài liệu…
      </p>
    );
  }

  if (loadState === "not_found" || !doc) {
    return (
      <div className="flex flex-col items-start gap-4">
        <h1 className="text-h1 text-text-primary">Không tìm thấy tài liệu</h1>
        <p className="text-body text-text-secondary">
          Tài liệu này không còn trong kho (có thể đã bị xóa).
        </p>
        <Link
          href="/admin/documents"
          className="inline-flex h-control items-center rounded-md border border-brand-navy bg-brand-navy px-4 text-label text-text-on-brand hover:opacity-90"
        >
          Về danh sách tài liệu
        </Link>
      </div>
    );
  }

  const processing = doc.status === "processing";

  function handleDownload() {
    if (!doc) return;
    if (USE_MOCK) {
      toast.info(
        "Đang ở chế độ dữ liệu mẫu",
        "Chưa có file gốc thật. Khi nối backend, nút này tải file từ /api/files/{doc_id}.",
      );
      return;
    }
    window.open(fileUrl(doc.doc_id), "_blank", "noopener,noreferrer");
    toast.success("Đang tải file gốc", doc.file);
  }

  async function confirmReindex() {
    if (!doc) return;
    setBusy(true);
    try {
      await reindexDocument(doc.doc_id);
      setReindexOpen(false);
      toast.info("Bắt đầu re-index", "Tiến trình hiển thị cạnh trạng thái tài liệu.");
    } catch {
      toast.error("Không re-index được", "Vui lòng thử lại sau.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!doc) return;
    setBusy(true);
    try {
      const res = await deleteDocument(doc.doc_id);
      toast.success(
        "Đã xóa tài liệu",
        `“${doc.title}” và ${res.deleted_chunks.toLocaleString("vi-VN")} chunk đã được gỡ khỏi Qdrant.`,
      );
      router.push("/admin/documents");
    } catch {
      setBusy(false);
      toast.error("Không xóa được tài liệu", "Vui lòng thử lại sau.");
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6">
      <div>
        <nav aria-label="Đường dẫn" className="flex items-center gap-2 text-body-sm text-text-tertiary">
          <Link href="/admin/documents" className="underline underline-offset-2 hover:text-brand-navy">
            Tài liệu
          </Link>
          <span aria-hidden="true">›</span>
          <span aria-current="page" className="truncate">
            {doc.title}
          </span>
        </nav>

        <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-h1 text-text-primary">{doc.title}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
              <Badge tone="file">{doc.type}</Badge>
              {processing ? (
                <>
                  <Badge tone="processing">Đang re-index</Badge>
                  <span role="status" className="text-caption text-text-tertiary">
                    Bước {doc.step ?? 1}/4 · {INDEX_STEP_SHORT_LABELS[doc.step ?? 1]}
                  </span>
                </>
              ) : doc.status === "error" ? (
                <>
                  <Badge tone="error">Lỗi</Badge>
                  {doc.error_message ? (
                    <span className="text-caption text-error-text">{doc.error_message}</span>
                  ) : null}
                </>
              ) : (
                <Badge tone="success">Đã index</Badge>
              )}
              <span className="break-all font-mono text-caption text-text-muted">{doc.file}</span>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button
              variant="secondary"
              icon={<Download size={16} aria-hidden="true" />}
              onClick={handleDownload}
            >
              Tải file gốc
            </Button>
            <Button
              variant="secondary"
              icon={<RefreshCw size={16} aria-hidden="true" />}
              disabled={processing}
              title={processing ? "Đang xử lý, chưa thể re-index" : undefined}
              onClick={() => setReindexOpen(true)}
            >
              Re-index
            </Button>
            <Button
              variant="danger-outline"
              icon={<Trash2 size={16} aria-hidden="true" />}
              disabled={processing}
              title={processing ? "Đang xử lý, chưa thể xóa" : undefined}
              onClick={() => setDeleteOpen(true)}
            >
              Xóa
            </Button>
          </div>
        </div>
      </div>

      <dl className="grid grid-cols-2 divide-x divide-border-divider overflow-hidden rounded-lg border border-border-default bg-bg-surface md:grid-cols-3 xl:grid-cols-6 [&>div]:border-b [&>div]:border-border-divider xl:[&>div]:border-b-0">
        <InfoCell label="doc_id">
          <span className="break-all font-mono text-body-sm">{doc.doc_id}</span>
        </InfoCell>
        <InfoCell label="Phiên bản">
          v{doc.version}
          {doc.replaces_version ? ` · thay thế v${doc.replaces_version}` : ""}
        </InfoCell>
        <InfoCell label="Danh mục">{getDocCategoryLabel(doc.category)}</InfoCell>
        <InfoCell label="Số trang">{doc.pages || "—"}</InfoCell>
        <InfoCell label="Số chunk">{doc.chunks.toLocaleString("vi-VN")}</InfoCell>
        <InfoCell label="Index lúc">{formatIndexedAt(doc.indexed_at)}</InfoCell>
      </dl>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <ChunkListPanel docId={doc.doc_id} refreshKey={`${doc.status}-${doc.indexed_at}`} />
        <RetrieveTestPanel docId={doc.doc_id} />
      </div>

      <Dialog
        open={reindexOpen}
        onOpenChange={setReindexOpen}
        title={`Re-index “${doc.title}”?`}
        description="Hệ thống sẽ đọc lại file gốc và tạo lại các chunk qua 4 bước. Chunk cũ được thay bằng chunk mới sau khi xử lý xong."
        footer={
          <>
            <Button variant="secondary" disabled={busy} onClick={() => setReindexOpen(false)}>
              Hủy
            </Button>
            <Button loading={busy} onClick={confirmReindex}>
              Re-index
            </Button>
          </>
        }
      />

      <Dialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Xóa “${doc.title}”?`}
        description={`${doc.chunks.toLocaleString("vi-VN")} chunk sẽ bị xóa khỏi Qdrant và trợ lý sẽ không còn dùng tài liệu này để trả lời. Không thể hoàn tác.`}
        footer={
          <>
            <Button variant="secondary" disabled={busy} onClick={() => setDeleteOpen(false)}>
              Hủy
            </Button>
            <Button variant="danger" loading={busy} onClick={confirmDelete}>
              Xóa tài liệu
            </Button>
          </>
        }
      />
    </div>
  );
}

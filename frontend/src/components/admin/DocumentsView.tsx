"use client";

import { FileSearch, Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { AddDocumentForm } from "@/components/admin/AddDocumentForm";
import { DocumentsTable } from "@/components/admin/DocumentsTable";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Input";
import { StatCard } from "@/components/ui/StatCard";
import { useToast } from "@/components/ui/Toast";
import { DOC_CATEGORIES } from "@/lib/constants";
import type { DocCategory, DocumentRow, DocumentStats, DocumentStatus } from "@/lib/types";
import {
  deleteDocument,
  listDocuments,
  reindexDocument,
  subscribeAdminData,
} from "@/services/admin.service";

const EMPTY_STATS: DocumentStats = {
  indexed_count: 0,
  total_chunks: 0,
  processing_count: 0,
  error_count: 0,
};

export function DocumentsView() {
  const toast = useToast();
  const [items, setItems] = useState<DocumentRow[]>([]);
  const [stats, setStats] = useState<DocumentStats>(EMPTY_STATS);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);

  const [q, setQ] = useState("");
  const [category, setCategory] = useState<DocCategory | "">("");
  const [status, setStatus] = useState<DocumentStatus | "">("");

  const [formOpen, setFormOpen] = useState(false);
  const [reindexTarget, setReindexTarget] = useState<DocumentRow | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentRow | null>(null);
  const [busy, setBusy] = useState(false);

  // Tải danh sách theo bộ lọc và cập nhật trực tiếp khi dữ liệu admin thay đổi (tiến trình 4 bước).
  useEffect(() => {
    let cancelled = false;
    function load() {
      listDocuments({ q, category, status }).then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setStats(res.stats);
        setTotal(res.total);
        setLoaded(true);
      });
    }
    load();
    const unsubscribe = subscribeAdminData(load);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [q, category, status]);

  const filtering = q.trim() !== "" || category !== "" || status !== "";

  function clearFilters() {
    setQ("");
    setCategory("");
    setStatus("");
  }

  async function confirmReindex() {
    if (!reindexTarget) return;
    setBusy(true);
    try {
      await reindexDocument(reindexTarget.doc_id);
      toast.info("Đã bắt đầu re-index", `“${reindexTarget.title}” đang được xử lý lại.`);
      setReindexTarget(null);
    } catch {
      toast.error("Không re-index được", "Vui lòng thử lại sau.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      const res = await deleteDocument(deleteTarget.doc_id);
      toast.success(
        "Đã xóa tài liệu",
        `“${deleteTarget.title}” và ${res.deleted_chunks.toLocaleString("vi-VN")} chunk đã được gỡ khỏi Qdrant.`,
      );
      setDeleteTarget(null);
    } catch {
      toast.error("Không xóa được tài liệu", "Vui lòng thử lại sau.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-h1 text-text-primary">Tài liệu</h1>
          <p className="mt-1 text-body-sm text-text-tertiary">
            Văn bản trong kho tri thức mà trợ lý dùng để trả lời sinh viên.
          </p>
        </div>
        <Button
          icon={<Plus size={18} aria-hidden="true" />}
          aria-expanded={formOpen}
          aria-controls="add-document-form"
          onClick={() => setFormOpen((open) => !open)}
        >
          Thêm tài liệu
        </Button>
      </header>

      <section aria-label="Số liệu tài liệu" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Tài liệu đã index" value={stats.indexed_count} />
        <StatCard label="Tổng số chunk trong Qdrant" value={stats.total_chunks} />
        <StatCard label="Đang xử lý" value={stats.processing_count} tone="navy" />
        <StatCard label="Lỗi xử lý" value={stats.error_count} tone="error" />
      </section>

      {formOpen ? <AddDocumentForm onClose={() => setFormOpen(false)} /> : null}

      <div className="flex flex-wrap gap-3">
        <div className="relative min-w-[240px] flex-1">
          <Search
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm theo tên tài liệu hoặc tên file"
            aria-label="Tìm theo tên tài liệu hoặc tên file"
            className="h-control w-full rounded-md border border-border-default bg-bg-surface pl-10 pr-3 text-body-sm text-text-primary placeholder:text-text-muted"
          />
        </div>
        <div className="w-full sm:w-[200px]">
          <Select
            aria-label="Lọc theo danh mục"
            value={category}
            onChange={(e) => setCategory(e.target.value as DocCategory | "")}
            className="text-body-sm"
          >
            <option value="">Tất cả danh mục</option>
            {DOC_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-[170px]">
          <Select
            aria-label="Lọc theo trạng thái"
            value={status}
            onChange={(e) => setStatus(e.target.value as DocumentStatus | "")}
            className="text-body-sm"
          >
            <option value="">Mọi trạng thái</option>
            <option value="indexed">Đã index</option>
            <option value="processing">Đang xử lý</option>
            <option value="error">Lỗi</option>
          </Select>
        </div>
      </div>

      {!loaded ? (
        <p role="status" className="text-body-sm text-text-muted">
          Đang tải danh sách tài liệu…
        </p>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border-default bg-bg-surface px-6 py-12 text-center">
          <FileSearch size={28} aria-hidden="true" className="text-text-muted" />
          <p className="text-body text-text-secondary">
            {filtering
              ? "Không có tài liệu nào khớp bộ lọc."
              : "Chưa có tài liệu nào. Bấm “Thêm tài liệu” để bắt đầu."}
          </p>
          {filtering ? (
            <Button variant="secondary" size="sm" onClick={clearFilters}>
              Xóa bộ lọc
            </Button>
          ) : null}
        </div>
      ) : (
        <>
          <DocumentsTable items={items} onReindex={setReindexTarget} onDelete={setDeleteTarget} />
          <p className="text-caption text-text-muted">
            Hiển thị {items.length} / {total} tài liệu
          </p>
        </>
      )}

      <Dialog
        open={reindexTarget !== null}
        onOpenChange={(open) => !open && setReindexTarget(null)}
        title={`Re-index “${reindexTarget?.title ?? ""}”?`}
        description="Hệ thống sẽ đọc lại file gốc và tạo lại các chunk. Chunk cũ được thay bằng chunk mới sau khi xử lý xong."
        footer={
          <>
            <Button variant="secondary" disabled={busy} onClick={() => setReindexTarget(null)}>
              Hủy
            </Button>
            <Button loading={busy} onClick={confirmReindex}>
              Re-index
            </Button>
          </>
        }
      />

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={`Xóa “${deleteTarget?.title ?? ""}”?`}
        description={`${(deleteTarget?.chunks ?? 0).toLocaleString("vi-VN")} chunk sẽ bị xóa khỏi Qdrant và trợ lý sẽ không còn dùng tài liệu này để trả lời. Không thể hoàn tác.`}
        footer={
          <>
            <Button variant="secondary" disabled={busy} onClick={() => setDeleteTarget(null)}>
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

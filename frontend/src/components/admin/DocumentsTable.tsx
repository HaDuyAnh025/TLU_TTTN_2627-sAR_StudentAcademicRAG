"use client";

import { RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { INDEX_STEP_SHORT_LABELS, getDocCategoryLabel } from "@/lib/constants";
import { formatUpdatedAt } from "@/lib/date-groups";
import type { DocumentRow } from "@/lib/types";

const TH = "px-4 py-3 text-left text-overline uppercase text-text-label";

function StatusCell({ doc }: { doc: DocumentRow }) {
  if (doc.status === "processing") {
    return (
      <div className="flex flex-col items-start gap-1">
        <Badge tone="processing">Đang xử lý</Badge>
        <span role="status" className="text-caption-sm text-text-tertiary">
          Bước {doc.step ?? 1}/4 · {INDEX_STEP_SHORT_LABELS[doc.step ?? 1]}
        </span>
      </div>
    );
  }
  if (doc.status === "error") {
    return (
      <div className="flex max-w-[260px] flex-col items-start gap-1">
        <Badge tone="error">Lỗi</Badge>
        {doc.error_message ? (
          <span className="text-caption-sm text-error-text">{doc.error_message}</span>
        ) : null}
      </div>
    );
  }
  return <Badge tone="success">Đã index</Badge>;
}

export interface DocumentsTableProps {
  items: DocumentRow[];
  onReindex: (doc: DocumentRow) => void;
  onDelete: (doc: DocumentRow) => void;
}

export function DocumentsTable({ items, onReindex, onDelete }: DocumentsTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-default bg-bg-surface">
      <table className="w-full min-w-[960px] border-collapse">
        <caption className="sr-only">Danh sách tài liệu trong kho tri thức</caption>
        <thead>
          <tr className="border-b border-border-default">
            <th scope="col" className={TH}>Tài liệu</th>
            <th scope="col" className={TH}>Danh mục</th>
            <th scope="col" className={TH}>Loại</th>
            <th scope="col" className={`${TH} text-right`}>Chunk</th>
            <th scope="col" className={TH}>Trạng thái</th>
            <th scope="col" className={TH}>Cập nhật</th>
            <th scope="col" className={`${TH} text-right`}>Thao tác</th>
          </tr>
        </thead>
        <tbody>
          {items.map((doc) => {
            const busy = doc.status === "processing";
            return (
              <tr key={doc.doc_id} className="border-b border-border-divider last:border-b-0">
                <td className="max-w-[340px] px-4 py-4 align-middle">
                  <Link
                    href={`/admin/documents/${encodeURIComponent(doc.doc_id)}`}
                    className="text-label text-text-primary underline underline-offset-2 hover:text-brand-navy"
                  >
                    {doc.title}
                  </Link>
                  <p className="mt-0.5 break-all font-mono text-caption-sm text-text-muted">{doc.file}</p>
                </td>
                <td className="px-4 py-4 align-middle text-body-sm text-text-secondary">
                  {getDocCategoryLabel(doc.category)}
                </td>
                <td className="px-4 py-4 align-middle">
                  <Badge tone="file">{doc.type}</Badge>
                </td>
                <td className="px-4 py-4 text-right align-middle text-body-sm tabular-nums text-text-primary">
                  {doc.chunks.toLocaleString("vi-VN")}
                </td>
                <td className="px-4 py-4 align-middle">
                  <StatusCell doc={doc} />
                </td>
                <td className="whitespace-nowrap px-4 py-4 align-middle text-body-sm text-text-secondary">
                  {formatUpdatedAt(doc.updated_at)}
                </td>
                <td className="px-4 py-4 align-middle">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      iconOnly
                      disabled={busy}
                      aria-label={`Re-index “${doc.title}”`}
                      title={busy ? "Đang xử lý, chưa thể re-index" : "Re-index"}
                      onClick={() => onReindex(doc)}
                    >
                      <RefreshCw size={18} aria-hidden="true" className="text-text-secondary" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      iconOnly
                      disabled={busy}
                      aria-label={`Xóa “${doc.title}”`}
                      title={busy ? "Đang xử lý, chưa thể xóa" : "Xóa"}
                      onClick={() => onDelete(doc)}
                    >
                      <Trash2 size={18} aria-hidden="true" className="text-error" />
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import { useEffect, useRef } from "react";
import { useToast } from "@/components/ui/Toast";
import type { DocumentRow } from "@/lib/types";
import { listDocuments, subscribeAdminData } from "@/services/admin.service";

/**
 * Không hiển thị gì; theo dõi trạng thái tài liệu ở mọi trang quản trị và bắn toast khi
 * một tài liệu chuyển từ "đang xử lý" sang "đã index" hoặc "lỗi".
 */
export function DocumentStatusToaster() {
  const toast = useToast();
  const previous = useRef<Map<string, DocumentRow> | null>(null);

  useEffect(() => {
    let cancelled = false;

    function check() {
      listDocuments().then(({ items }) => {
        if (cancelled) return;
        const prev = previous.current;
        if (prev) {
          for (const doc of items) {
            if (prev.get(doc.doc_id)?.status !== "processing") continue;
            if (doc.status === "indexed") {
              toast.success("Đã index xong", `“${doc.title}” đã sẵn sàng để trợ lý sử dụng.`);
            } else if (doc.status === "error") {
              toast.error("Xử lý thất bại", doc.error_message ?? `Không xử lý được “${doc.title}”.`);
            }
          }
        }
        previous.current = new Map(items.map((d) => [d.doc_id, d]));
      });
    }

    check();
    const unsubscribe = subscribeAdminData(check);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [toast]);

  return null;
}

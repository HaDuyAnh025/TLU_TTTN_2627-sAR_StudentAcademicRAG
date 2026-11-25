import { Suspense } from "react";
import { DocumentDetailView } from "@/components/admin/DocumentDetailView";

async function DocumentContent({
  params,
}: {
  params: PageProps<"/admin/documents/[docId]">["params"];
}) {
  const { docId } = await params;
  return <DocumentDetailView key={docId} docId={decodeURIComponent(docId)} />;
}

// Trang quản trị chỉ hiển thị sau khi AdminAuthGuard đọc token ở client (localStorage), nên
// static shell không chứa nội dung trang — cố ý để không lộ giao diện admin trước khi kiểm tra
// đăng nhập. Vì vậy tắt kiểm tra "instant navigation" cho segment này (cách [ignore] trong tài liệu Next).
export const instant = false;

export default function AdminDocumentDetailPage(props: PageProps<"/admin/documents/[docId]">) {
  return (
    <Suspense
      fallback={
        <p role="status" className="text-body text-text-muted">
          Đang tải thông tin tài liệu…
        </p>
      }
    >
      <DocumentContent params={props.params} />
    </Suspense>
  );
}

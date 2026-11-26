import { notFound } from "next/navigation";
import { DevComponentsView } from "@/components/dev/DevComponentsView";

// Trang kiểm thử nội bộ: chỉ truy cập được khi chạy dev; bản production trả 404.
export default function DevComponentsPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <DevComponentsView />;
}

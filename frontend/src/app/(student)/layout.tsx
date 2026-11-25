import { Suspense } from "react";
import { SidebarStudent } from "@/components/layout/SidebarStudent";

function SidebarFallback() {
  return (
    <aside
      aria-hidden="true"
      className="hidden w-sidebar-student shrink-0 border-r border-border-default bg-bg-surface md:block"
    />
  );
}

export default function StudentLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <Suspense fallback={<SidebarFallback />}>
        <SidebarStudent />
      </Suspense>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

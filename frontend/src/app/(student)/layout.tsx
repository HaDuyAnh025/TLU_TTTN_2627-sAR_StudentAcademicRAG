import { Suspense } from "react";
import { SidebarStudent } from "@/components/layout/SidebarStudent";

function SidebarFallback() {
  return (
    <aside
      aria-hidden="true"
      className="hidden w-sidebar-student shrink-0 border-r border-border-default bg-bg-surface lg:block"
    />
  );
}

export default function StudentLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col lg:flex-row">
      <Suspense fallback={<SidebarFallback />}>
        <SidebarStudent />
      </Suspense>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

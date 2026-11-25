import Link from "next/link";
import { BrandLogo } from "@/components/ui/BrandLogo";

// Tạm thời: màn 1 (WelcomeView) sẽ thay thế ở bước sau của giai đoạn 1.
export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-[960px] flex-col gap-6 px-6 py-16">
      <BrandLogo />
      <p className="text-body text-text-secondary">
        Màn hình chào đang được xây dựng.{" "}
        <Link href="/dev/components" className="font-semibold text-brand-navy underline">
          Xem các thành phần giao diện
        </Link>
      </p>
    </main>
  );
}

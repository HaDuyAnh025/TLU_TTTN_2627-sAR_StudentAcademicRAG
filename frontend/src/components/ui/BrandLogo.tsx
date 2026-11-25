import clsx from "clsx";
import Image from "next/image";

export interface BrandLogoProps {
  /** Dòng phụ dưới tên (mặc định "Đại học Thăng Long"; admin dùng "Quản trị"). */
  subtitle?: string;
  size?: number;
  className?: string;
}

export function BrandLogo({
  subtitle = "Đại học Thăng Long",
  size = 40,
  className,
}: BrandLogoProps) {
  return (
    <div className={clsx("flex items-center gap-3", className)}>
      <Image src="/logo-mark.svg" alt="" width={size} height={size} priority />
      <div className="min-w-0">
        <p className="text-h3 text-text-primary">Trợ lý Học vụ</p>
        <p className="text-caption text-text-muted">{subtitle}</p>
      </div>
    </div>
  );
}

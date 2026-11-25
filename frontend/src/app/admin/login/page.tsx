import type { Metadata } from "next";
import { AdminLoginForm } from "@/components/admin/AdminLoginForm";

export const metadata: Metadata = {
  title: "Đăng nhập quản trị — Trợ lý Học vụ",
};

export default function AdminLoginPage() {
  return <AdminLoginForm />;
}

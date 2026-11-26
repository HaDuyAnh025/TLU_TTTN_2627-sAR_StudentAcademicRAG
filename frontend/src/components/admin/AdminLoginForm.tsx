"use client";

import { AlertCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import type { FormEvent } from "react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { isInvalidCredentials, login } from "@/services/admin.service";

export function AdminLoginForm() {
  const router = useRouter();
  const errorId = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | undefined>();
  const [missing, setMissing] = useState({ username: false, password: false });
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const missingUsername = username.trim() === "";
    const missingPassword = password === "";
    if (missingUsername || missingPassword) {
      setMissing({ username: missingUsername, password: missingPassword });
      setFormError("Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.");
      document.getElementById(missingUsername ? "admin-username" : "admin-password")?.focus();
      return;
    }
    setMissing({ username: false, password: false });
    setFormError(undefined);
    setLoading(true);
    try {
      await login({ username: username.trim(), password });
      router.replace("/admin/documents");
    } catch (error) {
      setLoading(false);
      setFormError(
        isInvalidCredentials(error)
          ? "Tên đăng nhập hoặc mật khẩu không đúng. Vui lòng kiểm tra lại."
          : "Không đăng nhập được do mất kết nối tới máy chủ. Vui lòng thử lại.",
      );
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-10">
      <div className="flex w-full max-w-[420px] flex-col items-stretch gap-6">
        <BrandLogo subtitle="Khu vực quản trị dữ liệu" size={44} className="justify-center" />

        <div className="rounded-xl border border-border-default bg-bg-surface p-8">
          <h1 className="text-h1 text-text-primary">Đăng nhập quản trị</h1>
          <p className="mt-1 text-body-sm text-text-tertiary">
            Dành cho người quản lý kho tài liệu và phản hồi.
          </p>

          <form onSubmit={handleSubmit} noValidate className="mt-5 flex flex-col gap-4">
            {formError ? (
              <div
                id={errorId}
                role="alert"
                className="flex items-start gap-2 rounded-md border border-error-border bg-error-bg px-3 py-3 text-body-sm font-semibold text-error-text"
              >
                <AlertCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
                {formError}
              </div>
            ) : null}

            <Input
              id="admin-username"
              label="Tên đăng nhập"
              name="username"
              autoComplete="username"
              value={username}
              invalid={missing.username}
              aria-describedby={formError ? errorId : undefined}
              onChange={(e) => {
                setUsername(e.target.value);
                if (missing.username) setMissing((m) => ({ ...m, username: false }));
              }}
            />
            <Input
              id="admin-password"
              label="Mật khẩu"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              invalid={missing.password}
              aria-describedby={formError ? errorId : undefined}
              onChange={(e) => {
                setPassword(e.target.value);
                if (missing.password) setMissing((m) => ({ ...m, password: false }));
              }}
            />
            <Button type="submit" fullWidth loading={loading}>
              {loading ? "Đang đăng nhập…" : "Đăng nhập"}
            </Button>
          </form>
        </div>

        <p className="text-center text-body-sm text-text-tertiary">
          Bạn là sinh viên? Không cần đăng nhập —{" "}
          <Link href="/" className="font-medium text-brand-navy underline">
            về trang tra cứu
          </Link>
          .
        </p>
      </div>
    </main>
  );
}

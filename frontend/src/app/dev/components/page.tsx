"use client";

import { Download, Plus, RotateCcw, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import type { ButtonVariant } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Dialog } from "@/components/ui/Dialog";
import { Input, Select, Textarea } from "@/components/ui/Input";
import { StatCard } from "@/components/ui/StatCard";
import { useToast } from "@/components/ui/Toast";
import { DOC_CATEGORIES, FEEDBACK_REASONS } from "@/lib/constants";
import { resetMockData } from "@/services/mock";

const VARIANTS: ButtonVariant[] = ["primary", "secondary", "danger", "ghost"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border-default bg-bg-surface p-6">
      <h2 className="mb-4 text-overline uppercase text-text-label">{title}</h2>
      <div className="flex flex-wrap items-start gap-4">{children}</div>
    </section>
  );
}

export default function DevComponentsPage() {
  const toast = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pressedChip, setPressedChip] = useState<string>("wrong_info");
  const [showErrors, setShowErrors] = useState(true);

  function handleReset() {
    resetMockData();
    toast.success("Đã reset dữ liệu mẫu", "Toàn bộ khóa sar_mock_* trong localStorage đã được xóa.");
  }

  return (
    <main className="mx-auto flex w-full max-w-[960px] flex-col gap-6 px-6 py-10">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-h1 text-text-primary">Thành phần giao diện dùng chung</h1>
          <p className="mt-1 text-body-sm text-text-muted">
            Trang kiểm thử nội bộ — hiển thị mọi biến thể để đối chiếu với SPEC.
          </p>
        </div>
        <Button variant="secondary" icon={<RotateCcw size={16} aria-hidden="true" />} onClick={handleReset}>
          Reset dữ liệu mẫu
        </Button>
      </header>

      <Section title="Logo">
        <BrandLogo />
        <BrandLogo subtitle="Quản trị" />
      </Section>

      <Section title="Button — md 44px">
        {VARIANTS.map((v) => (
          <Button key={v} variant={v}>
            {v}
          </Button>
        ))}
        <Button icon={<Plus size={16} aria-hidden="true" />}>Có icon</Button>
        <Button loading>Đang tải lên…</Button>
        <Button disabled>Vô hiệu hóa</Button>
        <Button iconOnly variant="secondary" aria-label="Tìm kiếm">
          <Search size={18} aria-hidden="true" />
        </Button>
      </Section>

      <Section title="Button — sm 40px">
        {VARIANTS.map((v) => (
          <Button key={v} variant={v} size="sm">
            {v}
          </Button>
        ))}
        <Button size="sm" icon={<Download size={16} aria-hidden="true" />}>
          Tải file gốc
        </Button>
        <Button size="sm" loading>
          Đang xử lý
        </Button>
        <Button size="sm" disabled>
          Vô hiệu hóa
        </Button>
        <Button size="sm" iconOnly variant="secondary" aria-label="Xóa">
          <Trash2 size={18} aria-hidden="true" />
        </Button>
      </Section>

      <Section title="Input / Textarea / Select">
        <div className="flex w-full flex-wrap gap-4">
          <div className="min-w-[260px] flex-1">
            <Input label="Tên đăng nhập" placeholder="admin" autoComplete="username" />
          </div>
          <div className="min-w-[260px] flex-1">
            <Input
              label="Mật khẩu"
              type="password"
              autoComplete="current-password"
              error={showErrors ? "Vui lòng nhập mật khẩu." : undefined}
            />
          </div>
          <div className="min-w-[260px] flex-1">
            <Select label="Danh mục" defaultValue="quy_che">
              {DOC_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-[260px] flex-1">
            <Select label="Danh mục (lỗi)" defaultValue="" error={showErrors ? "Vui lòng chọn danh mục." : undefined}>
              <option value="">— Chọn —</option>
              {DOC_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="w-full">
            <Textarea
              label="Mô tả lý do"
              placeholder="Nhập mô tả…"
              hint="Bắt buộc khi chọn lý do “Khác”."
            />
          </div>
          <div className="w-full">
            <Textarea
              label="Câu hỏi"
              error={showErrors ? "Vui lòng nhập câu hỏi trước khi gửi." : undefined}
            />
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setShowErrors((s) => !s)}>
          {showErrors ? "Ẩn" : "Hiện"} trạng thái lỗi
        </Button>
      </Section>

      <Section title="Badge">
        <Badge tone="success">Đã index</Badge>
        <Badge tone="processing">Đang xử lý</Badge>
        <Badge tone="error">Lỗi</Badge>
        <Badge tone="file">PDF</Badge>
        <Badge tone="file">Web</Badge>
        <Badge tone="file">Ảnh</Badge>
        <Badge tone="success" icon={false}>Đúng</Badge>
        <Badge tone="error" icon={false}>Sai</Badge>
        <Badge tone="neutral">Bảng · 1 dòng = 1 câu</Badge>
      </Section>

      <Section title="Chip (aria-pressed)">
        {FEEDBACK_REASONS.map((r) => (
          <Chip
            key={r.value}
            pressed={pressedChip === r.value}
            onClick={() => setPressedChip(r.value)}
          >
            {r.label}
          </Chip>
        ))}
      </Section>

      <Section title="StatCard">
        <div className="grid w-full grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Tài liệu đã index" value={24} />
          <StatCard label="Tổng số chunk trong Qdrant" value={1842} />
          <StatCard label="Đang xử lý" value={2} tone="navy" />
          <StatCard label="Lỗi xử lý" value={1} tone="error" />
        </div>
      </Section>

      <Section title="Toast (góc dưới phải, tự ẩn 5 giây)">
        <Button
          variant="secondary"
          onClick={() => toast.success("Đã gửi phản hồi", "Cảm ơn bạn! Phản hồi sẽ được dùng để cải thiện câu trả lời.")}
        >
          Toast thành công
        </Button>
        <Button
          variant="secondary"
          onClick={() => toast.error("Không gửi được câu hỏi", "Mất kết nối tới máy chủ. Vui lòng thử lại.")}
        >
          Toast lỗi
        </Button>
        <Button
          variant="secondary"
          onClick={() => toast.info("Đã sao chép", "Nội dung câu trả lời đã được sao chép.")}
        >
          Toast thông tin
        </Button>
      </Section>

      <Section title="Dialog">
        <Button variant="secondary" onClick={() => setDialogOpen(true)}>
          Mở hộp thoại xóa
        </Button>
      </Section>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Xóa cuộc trò chuyện này?"
        description="“Điều kiện xét tốt nghiệp” sẽ bị xóa khỏi lịch sử. Bạn sẽ được đưa về màn hình bắt đầu."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDialogOpen(false)}>
              Hủy
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setDialogOpen(false);
                toast.success("Đã xóa hội thoại");
              }}
            >
              Xóa hội thoại
            </Button>
          </>
        }
      />
    </main>
  );
}

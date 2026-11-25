"use client";

import clsx from "clsx";
import { FileText, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import { DOC_CATEGORIES, INDEX_STEP_LABELS } from "@/lib/constants";
import { formatBytes } from "@/lib/date-groups";
import type { DocCategory, IndexStep } from "@/lib/types";
import { addDocument } from "@/services/admin.service";

type Tab = "file" | "url";

interface PickedFile {
  key: string;
  name: string;
  size: number;
  valid: boolean;
}

const ACCEPTED_EXTENSIONS = ["pdf", "png", "jpg", "jpeg"];
const STEPS: IndexStep[] = [1, 2, 3, 4];

function isAcceptedFile(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return ACCEPTED_EXTENSIONS.includes(ext);
}

/** "quy-che-dao-tao.pdf" → "Quy che dao tao" */
function titleFromFileName(name: string): string {
  const base = name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "";
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

interface FormErrors {
  files?: string;
  url?: string;
  title?: string;
}

export interface AddDocumentFormProps {
  onClose: () => void;
}

export function AddDocumentForm({ onClose }: AddDocumentFormProps) {
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState<Tab>("file");
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [titleTouched, setTitleTouched] = useState(false);
  const [category, setCategory] = useState<DocCategory>("quy_che");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const validFiles = files.filter((f) => f.valid);

  function syncTitle(next: PickedFile[]) {
    if (titleTouched) return;
    const first = next.find((f) => f.valid);
    setTitle(first ? titleFromFileName(first.name) : "");
  }

  function addFiles(list: FileList | File[]) {
    const picked: PickedFile[] = Array.from(list).map((f, i) => ({
      key: `${f.name}-${f.size}-${Date.now()}-${i}`,
      name: f.name,
      size: f.size,
      valid: isAcceptedFile(f.name),
    }));
    if (picked.length === 0) return;
    const next = [...files, ...picked];
    setFiles(next);
    setErrors((e) => ({ ...e, files: undefined, title: undefined }));
    syncTitle(next);
  }

  function removeFile(key: string) {
    const next = files.filter((f) => f.key !== key);
    setFiles(next);
    setErrors((e) => ({ ...e, files: undefined }));
    syncTitle(next);
  }

  function handleInputChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files) addFiles(e.target.files);
    e.target.value = "";
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  }

  function validate(): FormErrors {
    const next: FormErrors = {};
    if (tab === "file") {
      if (files.length === 0) {
        next.files = "Chưa chọn file. Hãy chọn ít nhất một file PDF hoặc ảnh.";
      } else if (files.some((f) => !f.valid)) {
        next.files = "Có file sai định dạng. Hãy xóa file đó hoặc chọn lại (chỉ nhận PDF, PNG, JPG).";
      }
    } else if (url.trim() === "") {
      next.url = "Vui lòng nhập đường link trang web.";
    } else if (!isHttpUrl(url.trim())) {
      next.url = "Đường link phải bắt đầu bằng http:// hoặc https://.";
    }
    if (title.trim() === "") next.title = "Vui lòng nhập tên hiển thị.";
    return next;
  }

  async function handleSubmit() {
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      toast.error("Chưa thể thêm tài liệu", "Vui lòng sửa các ô được đánh dấu đỏ.");
      return;
    }
    setSubmitting(true);
    try {
      const common = {
        category,
        effective_date: effectiveDate || undefined,
        replace_existing: replaceExisting,
      };
      if (tab === "url") {
        await addDocument({ source: "url", url: url.trim(), title: title.trim(), ...common });
      } else {
        for (const [index, file] of validFiles.entries()) {
          await addDocument({
            source: "file",
            file_name: file.name,
            file_size: file.size,
            title: index === 0 ? title.trim() : titleFromFileName(file.name),
            ...common,
          });
        }
      }
      toast.success(
        "Đã nhận tài liệu",
        "Tài liệu đang được xử lý — theo dõi tiến trình trong bảng bên dưới.",
      );
      onClose();
    } catch {
      setSubmitting(false);
      toast.error("Không tải lên được", "Mất kết nối tới máy chủ. Vui lòng thử lại.");
    }
  }

  return (
    <section
      id="add-document-form"
      aria-labelledby="add-document-title"
      className="rounded-xl border-2 border-brand-navy bg-bg-surface p-6"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="add-document-title" className="text-h2 text-text-primary">
          Thêm tài liệu mới
        </h2>
        <Button variant="ghost" iconOnly size="sm" aria-label="Đóng form thêm tài liệu" onClick={onClose}>
          <X size={18} aria-hidden="true" className="text-text-secondary" />
        </Button>
      </div>

      <div
        role="group"
        aria-label="Nguồn tài liệu"
        className="mt-4 inline-flex gap-1 rounded-md bg-bg-subtle p-1"
      >
        {(
          [
            ["file", "Tải file lên"],
            ["url", "Từ đường link web"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={tab === value}
            onClick={() => setTab(value)}
            className={clsx(
              "h-control-sm cursor-pointer rounded-sm px-4 text-body-sm",
              tab === value
                ? "bg-bg-surface font-semibold text-text-primary shadow-sm"
                : "text-text-tertiary hover:text-text-primary",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-5 grid gap-6 md:grid-cols-2">
        <div>
          {tab === "file" ? (
            <>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                className={clsx(
                  "flex min-h-[168px] flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center",
                  errors.files ? "border-error" : "border-border-strong",
                  dragging && "bg-brand-navy-soft",
                )}
              >
                <Upload size={24} aria-hidden="true" className="text-text-secondary" />
                <p className="text-label text-text-primary">
                  Kéo thả file vào đây hoặc{" "}
                  <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    className="cursor-pointer font-semibold text-brand-navy underline"
                  >
                    chọn file
                  </button>
                </p>
                <p className="text-caption text-text-muted">
                  PDF, PNG, JPG · ảnh ngang hoặc dọc đều được
                </p>
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={handleInputChange}
                  tabIndex={-1}
                  aria-label="Chọn file tài liệu"
                  className="sr-only"
                />
              </div>
              {errors.files ? (
                <p role="alert" className="mt-2 text-caption font-semibold text-error-text">
                  {errors.files}
                </p>
              ) : null}
              {files.length > 0 ? (
                <ul className="mt-3 flex flex-col gap-2" aria-label="File đã chọn">
                  {files.map((f) => (
                    <li
                      key={f.key}
                      className="flex items-center gap-3 rounded-md border border-border-default px-3 py-2"
                    >
                      <FileText size={16} aria-hidden="true" className="shrink-0 text-text-tertiary" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-body-sm text-text-primary">{f.name}</span>
                        <span className="text-caption-sm text-text-muted">{formatBytes(f.size)}</span>
                      </span>
                      <Badge tone={f.valid ? "success" : "error"}>
                        {f.valid ? "Hợp lệ" : "Sai định dạng"}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        iconOnly
                        aria-label={`Bỏ file ${f.name}`}
                        onClick={() => removeFile(f.key)}
                      >
                        <X size={16} aria-hidden="true" className="text-text-secondary" />
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <Input
              label="Đường link trang web"
              type="url"
              inputMode="url"
              placeholder="https://thanglong.edu.vn/thong-bao/…"
              value={url}
              error={errors.url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (errors.url) setErrors((v) => ({ ...v, url: undefined }));
              }}
            />
          )}
        </div>

        <div className="flex flex-col gap-4">
          <Input
            label="Tên hiển thị trong trích dẫn"
            placeholder="Ví dụ: Quy chế đào tạo trình độ đại học"
            value={title}
            error={errors.title}
            hint={
              tab === "file" && validFiles.length > 1
                ? "Tên này áp dụng cho file đầu tiên; các file còn lại lấy tên từ tên file."
                : undefined
            }
            onChange={(e) => {
              setTitle(e.target.value);
              setTitleTouched(true);
              if (errors.title) setErrors((v) => ({ ...v, title: undefined }));
            }}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="Danh mục"
              value={category}
              onChange={(e) => setCategory(e.target.value as DocCategory)}
            >
              {DOC_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
            <Input
              label="Ngày hiệu lực"
              type="date"
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
            />
          </div>
          <label className="flex cursor-pointer items-start gap-3 text-body-sm text-text-secondary">
            <input
              type="checkbox"
              checked={replaceExisting}
              onChange={(e) => setReplaceExisting(e.target.checked)}
              className="mt-1 size-4 shrink-0 cursor-pointer accent-brand-navy"
            />
            Đây là bản mới thay thế cho một tài liệu đã có. Các chunk của bản cũ sẽ bị gỡ khỏi index
            sau khi bản mới xử lý xong.
          </label>
        </div>
      </div>

      <ol className="mt-6 flex flex-wrap gap-x-5 gap-y-2 rounded-lg bg-bg-page px-4 py-3">
        {STEPS.map((step) => (
          <li key={step} className="flex items-center gap-2 text-caption text-text-secondary">
            <span
              aria-hidden="true"
              className="flex size-5 shrink-0 items-center justify-center rounded-full border border-border-strong bg-bg-surface text-caption-sm font-semibold"
            >
              {step}
            </span>
            {INDEX_STEP_LABELS[step]}
          </li>
        ))}
      </ol>

      <div className="mt-5 flex justify-end gap-3">
        <Button variant="secondary" disabled={submitting} onClick={onClose}>
          Hủy
        </Button>
        <Button loading={submitting} onClick={handleSubmit}>
          {submitting ? "Đang tải lên…" : "Xử lý & đưa vào index"}
        </Button>
      </div>
    </section>
  );
}

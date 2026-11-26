"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import clsx from "clsx";
import type { ReactNode } from "react";
import { useReturnFocus } from "@/lib/use-return-focus";

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  /** Vùng nút bấm (Hủy / Xác nhận). */
  footer?: ReactNode;
  /** Lớp chiều rộng tối đa của thẻ, mặc định 440px. */
  widthClassName?: string;
  children?: ReactNode;
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  footer,
  widthClassName = "max-w-[440px]",
  children,
}: DialogProps) {
  const { onOpenAutoFocus, onCloseAutoFocus } = useReturnFocus();
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <RadixDialog.Content
          onOpenAutoFocus={onOpenAutoFocus}
          onCloseAutoFocus={onCloseAutoFocus}
          {...(description ? {} : { "aria-describedby": undefined })}
          className={clsx(
            "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2",
            "max-h-[calc(100vh-32px)] overflow-y-auto rounded-xl bg-bg-surface p-6 shadow-dialog",
            widthClassName,
          )}
        >
          <RadixDialog.Title className="text-h2 text-text-primary">{title}</RadixDialog.Title>
          {description ? (
            <RadixDialog.Description className="mt-3 text-body-sm text-text-secondary">
              {description}
            </RadixDialog.Description>
          ) : null}
          {children ? <div className="mt-4">{children}</div> : null}
          {footer ? (
            <div className="mt-6 flex flex-wrap justify-end gap-3">{footer}</div>
          ) : null}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

export const DialogClose = RadixDialog.Close;

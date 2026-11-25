"use client";

import clsx from "clsx";
import { AlertCircle, Check, Info, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

export type ToastKind = "success" | "error" | "info";

export interface ToastInput {
  kind?: ToastKind;
  title: string;
  message?: string;
}

interface ToastItem extends ToastInput {
  id: number;
  kind: ToastKind;
}

interface ToastApi {
  toast: (input: ToastInput) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export const TOAST_DURATION_MS = 5000;

const KIND_STYLES: Record<ToastKind, string> = {
  success: "bg-success-strong",
  error: "bg-error-text",
  info: "bg-brand-navy",
};

const KIND_ICONS = {
  success: Check,
  error: AlertCircle,
  info: Info,
} as const;

function ToastCard({
  item,
  onClose,
}: {
  item: ToastItem;
  onClose: (id: number) => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(() => onClose(item.id), TOAST_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [item.id, onClose]);

  const Icon = KIND_ICONS[item.kind];
  return (
    <div
      role="status"
      aria-live="polite"
      className={clsx(
        "pointer-events-auto flex w-full items-start gap-3 rounded-lg p-4 text-text-on-brand shadow-toast",
        KIND_STYLES[item.kind],
      )}
    >
      <Icon size={20} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-label">{item.title}</p>
        {item.message ? <p className="mt-0.5 text-body-sm">{item.message}</p> : null}
      </div>
      <button
        type="button"
        aria-label="Đóng thông báo"
        onClick={() => onClose(item.id)}
        className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-sm bg-white/15 hover:bg-white/25"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const close = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((input: ToastInput) => {
    const id = nextId.current++;
    setItems((prev) => [...prev, { ...input, id, kind: input.kind ?? "info" }]);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      success: (title, message) => toast({ kind: "success", title, message }),
      error: (title, message) => toast({ kind: "error", title, message }),
      info: (title, message) => toast({ kind: "info", title, message }),
    }),
    [toast],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-6 right-6 z-[60] flex w-[400px] max-w-[calc(100vw-32px)] flex-col gap-3">
        {items.map((item) => (
          <ToastCard key={item.id} item={item} onClose={close} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast phải được dùng bên trong <ToastProvider>.");
  return ctx;
}

import { useCallback, useRef } from "react";

/**
 * Radix Dialog chỉ trả focus về nút mở khi dùng <Dialog.Trigger>. Các hộp thoại của dự án mở bằng state
 * (controlled), nên hook này nhớ phần tử đang focus lúc mở và trả focus về khi đóng (SPEC mục 7).
 */
export function useReturnFocus() {
  const openerRef = useRef<HTMLElement | null>(null);

  const onOpenAutoFocus = useCallback(() => {
    const active = document.activeElement;
    openerRef.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, []);

  const onCloseAutoFocus = useCallback((event: Event) => {
    event.preventDefault();
    const opener = openerRef.current;
    openerRef.current = null;
    if (opener?.isConnected) opener.focus();
  }, []);

  return { onOpenAutoFocus, onCloseAutoFocus };
}

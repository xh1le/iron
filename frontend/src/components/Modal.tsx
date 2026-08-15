import { useEffect, useRef, useState } from "react";

type Props = {
  open: boolean;
  title: string;
  placeholder?: string;
  confirmLabel?: string;
  initial?: string;
  onClose: () => void;
  onConfirm: (value: string) => void;
};

export default function Modal({ open, title, placeholder, confirmLabel = "create", initial = "", onClose, onConfirm }: Props) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    setValue(initial);
    setTimeout(() => ref.current?.querySelector<HTMLInputElement>("input")?.focus(), 30);
    return () => prev?.focus?.();
  }, [open, initial]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const focusables = ref.current?.querySelectorAll<HTMLElement>("button, input, select, textarea, a[href]") || [];
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && (active === first || !ref.current?.contains(active))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" ref={ref} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) onConfirm(value.trim()); }} />
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>cancel</button>
          <button type="button" className="solid" disabled={!value.trim()} onClick={() => onConfirm(value.trim())}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

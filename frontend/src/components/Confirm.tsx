import { useEffect, useRef, useState } from "react";

type Props = {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  onClose: () => void;
  onConfirm: () => void;
};

export default function Confirm({ open, title, body, confirmLabel = "delete", onClose, onConfirm }: Props) {
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    setBusy(false);
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
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);

  useEffect(() => { if (open) ref.current?.focus(); }, [open]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()} role="alertdialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <p className="modal-body">{body}</p>
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>cancel</button>
          <button type="button" className="solid danger-solid" disabled={busy} onClick={() => { setBusy(true); onConfirm(); }}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

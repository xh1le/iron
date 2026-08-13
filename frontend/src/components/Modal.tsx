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
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => { if (open) { setValue(initial); setTimeout(() => ref.current?.focus(), 30); } }, [open, initial]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <input ref={ref} value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) onConfirm(value.trim()); }} />
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>cancel</button>
          <button type="button" className="solid" disabled={!value.trim()} onClick={() => onConfirm(value.trim())}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Props = {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder?: string;
};

export default function ModelPicker({ value, options, onChange, placeholder = "auto" }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ bottom: number; left: number; width: number } | null>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Element;
      if (ref.current?.contains(t)) return;
      if (t.closest?.(".model-menu")) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
  }, []);

  useEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const width = Math.max(r.width, 200);
    const left = Math.min(r.left, window.innerWidth - width - 8);
    setPos({ bottom: window.innerHeight - r.top + 8, left: Math.max(8, left), width });
    const onScroll = (e: Event) => {
      const t = e.target as Element | null;
      if (t instanceof Element && t.closest(".model-menu")) return;
      setOpen(false);
    };
    const onResize = () => setOpen(false);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", onResize); };
  }, [open]);

  const all = ["", ...options];
  const display = value ? value : placeholder;

  const menu = open && pos ? (
    <div className="model-menu" role="listbox" style={{ position: "fixed", left: pos.left, width: pos.width, bottom: pos.bottom, zIndex: 9999, opacity: 1, transform: "none", pointerEvents: "auto" }}>
      {all.map((opt, i) => {
        const isActive = (opt || "") === (value || "");
        const name = opt || placeholder;
        return (
          <button
            key={opt || "__auto"}
            role="option"
            aria-selected={isActive}
            className={`model-option ${isActive ? "active" : ""}`}
            style={{ ["--i" as any]: i } as any}
            onClick={() => { onChange(opt); setOpen(false); }}
          >
            <span className="model-name">{name}</span>
            {isActive && <span className="check">✓</span>}
          </button>
        );
      })}
    </div>
  ) : null;

  return (
    <div ref={ref} className={`model-picker ${open ? "open" : ""}`}>
      <button type="button" className="model-trigger" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="dot-mini" aria-hidden="true" />
        <span className="model-label">{display}</span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">▾</span>
      </button>
      {menu && createPortal(menu, document.body)}
    </div>
  );
}

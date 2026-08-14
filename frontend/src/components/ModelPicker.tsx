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
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number; width: number } | null>(null);

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
    const estH = Math.min(260, (options.length + 1) * 36 + 12);
    const spaceBelow = window.innerHeight - r.bottom;
    const spaceAbove = r.top;
    const below = spaceBelow > estH || spaceBelow > spaceAbove;
    if (below) {
      setPos({ top: r.bottom + 8, left: r.left, width: Math.max(r.width, 220) } as any);
    } else {
      setPos({ bottom: window.innerHeight - r.top + 8, left: r.left, width: Math.max(r.width, 220) } as any);
    }
    const onScroll = (e: Event) => {
      const t = e.target as Element | null;
      if (t instanceof Element && t.closest(".model-menu")) return;
      setOpen(false);
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => { window.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", onScroll); };
  }, [open, options.length]);

  const all = ["", ...options];

  const menu = open && pos ? (
    <div
      className="model-menu"
      role="listbox"
      style={{
        position: "fixed",
        left: pos.left,
        width: pos.width,
        top: (pos as any).top,
        bottom: (pos as any).bottom,
        zIndex: 9999,
        opacity: 1,
        transform: "none",
        pointerEvents: "auto",
      } as any}
    >
      {all.map((opt, i) => {
        const isActive = (opt || "") === (value || "");
        const name = opt || placeholder;
        return (
          <button key={opt || "__auto"} role="option" aria-selected={isActive} className={`model-option ${isActive ? "active" : ""}`} style={{ ["--i" as any]: i } as any} onClick={() => { onChange(opt); setOpen(false); }}>
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
        <span className="model-label">{value || placeholder}</span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">▾</span>
      </button>
      {menu && createPortal(menu, document.body)}
    </div>
  );
}

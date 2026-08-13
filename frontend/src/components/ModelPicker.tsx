import { useEffect, useRef, useState } from "react";

type Props = {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder?: string;
};

export default function ModelPicker({ value, options, onChange, placeholder = "auto" }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
  }, []);

  const all = ["", ...options];
  const label = value || placeholder;
  const display = value ? value : placeholder;

  return (
    <div ref={ref} className={`model-picker ${open ? "open" : ""}`}>
      <button type="button" className="model-trigger" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="dot-mini" aria-hidden="true" />
        <span className="model-label">{display}</span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">▾</span>
      </button>
      <div className="model-menu" role="listbox">
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
    </div>
  );
}

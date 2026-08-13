import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Project } from "../types";

type Props = {
  projects: Project[];
  value: string;
  onChange: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
};

export default function ProjectPicker({ projects, value, onChange, onDelete, onNew }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const current = projects.find((p) => p.id === value);

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
    const MENU_H = 260;
    const below = r.bottom + 8;
    const top = below + MENU_H > window.innerHeight ? Math.max(8, r.top - 8 - MENU_H) : below;
    const width = Math.max(r.width, 200);
    const left = Math.min(r.left, window.innerWidth - width - 8);
    setPos({ top, left: Math.max(8, left), width });
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

  const menu = open && pos ? (
    <div className="model-menu project-menu" role="listbox" style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width, bottom: "auto", zIndex: 9999, opacity: 1, transform: "none", pointerEvents: "auto" }}>
      {projects.map((p, i) => (
        <div key={p.id} className={`project-row ${p.id === value ? "active" : ""}`} style={{ ["--i" as any]: i } as any}>
          <button role="option" aria-selected={p.id === value} className="model-option project-option" onClick={() => { onChange(p.id); setOpen(false); }}>
            <span className="model-name">{p.name}</span>
            {p.id === value && <span className="check">✓</span>}
          </button>
          {projects.length > 1 && (
            <button type="button" className="icon-mini danger" title="delete project" onClick={(e) => { e.stopPropagation(); onDelete(p.id); }}>
              ×
            </button>
          )}
        </div>
      ))}
      <button type="button" className="model-option new-project" onClick={() => { setOpen(false); onNew(); }}>
        + new project
      </button>
    </div>
  ) : null;

  return (
    <div ref={ref} className={`model-picker project-picker ${open ? "open" : ""}`}>
      <button type="button" className="model-trigger project-trigger" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="model-label">{current?.name || "home"}</span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">▾</span>
      </button>
      {menu && createPortal(menu, document.body)}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
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
  const current = projects.find((p) => p.id === value);

  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
  }, []);

  return (
    <div ref={ref} className={`model-picker project-picker ${open ? "open" : ""}`}>
      <button type="button" className="model-trigger project-trigger" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="model-label">{current?.name || "home"}</span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="model-menu project-menu" role="listbox">
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
      )}
    </div>
  );
}

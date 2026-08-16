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

function shortPath(path: string): string {
  if (!path) return "";
  // show last 2 segments for readability, or full if short
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  if (parts.length <= 2) return path;
  return "…/" + parts.slice(-2).join("/");
}

export default function ProjectPicker({ projects, value, onChange, onDelete, onNew }: Props) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number | string; bottom: number | string; left: number; width: number; maxHeight: number } | null>(null);
  const current = projects.find((p) => p.id === value);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Element;
      if (ref.current?.contains(t)) return;
      if (t.closest?.(".project-menu")) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      if (!open) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, projects.length));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && activeIndex >= 0) {
        e.preventDefault();
        if (activeIndex < projects.length) {
          onChange(projects[activeIndex].id);
          setOpen(false);
        } else {
          onNew();
          setOpen(false);
        }
      }
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, activeIndex, projects, onChange, onNew]);

  useEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const estH = Math.min(320, (projects.length + 1) * 48 + 16);
    const spaceBelow = window.innerHeight - r.bottom;
    const spaceAbove = r.top;
    const below = spaceBelow > estH || spaceBelow > spaceAbove;
    const width = Math.min(Math.max(r.width, 240), window.innerWidth - 24);
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    if (below) {
      setPos({ top: r.bottom + 8, bottom: "auto", left, width, maxHeight: Math.max(120, window.innerHeight - r.bottom - 8) });
    } else {
      setPos({ top: "auto", bottom: window.innerHeight - r.top + 8, left, width, maxHeight: Math.max(120, r.top - 8) });
    }
    const onScroll = (e: Event) => {
      const t = e.target as Element | null;
      if (t instanceof Element && t.closest(".project-menu")) return;
      setOpen(false);
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, projects.length]);

  useEffect(() => {
    if (open) setActiveIndex(projects.findIndex((p) => p.id === value));
  }, [open, value, projects]);

  const menu =
    open && pos ? (
      <div
        className="model-menu project-menu"
        role="listbox"
        style={{
          position: "fixed",
          left: pos.left,
          width: pos.width,
          top: pos.top,
          bottom: pos.bottom,
          maxHeight: pos.maxHeight,
          zIndex: 9999,
          opacity: 1,
          transform: "none",
          pointerEvents: "auto",
        }}
      >
        {projects.map((p, i) => (
          <div
            key={p.id}
            className={`project-row ${p.id === value ? "active" : ""} ${i === activeIndex ? "kbd-active" : ""}`}
            style={{ ["--i" as any]: i } as any}
          >
            <button
              role="option"
              aria-selected={p.id === value}
              className="model-option project-option"
              onClick={() => {
                onChange(p.id);
                setOpen(false);
              }}
              onMouseEnter={() => setActiveIndex(i)}
              title={`${p.name}\n${p.workspace || "no folder"}`}
            >
              <span className="project-option-main">
                <span className="project-folder-icon" aria-hidden="true">
                  {p.id === value ? "📂" : "📁"}
                </span>
                <span className="project-option-text">
                  <span className="model-name">{p.name}</span>
                  <span className="project-path mono" title={p.workspace}>
                    {p.workspace ? shortPath(p.workspace) : "no folder"}
                  </span>
                </span>
              </span>
              {p.id === value && <span className="check">✓</span>}
            </button>
            {projects.length > 1 && (
              <button
                type="button"
                className="icon-mini danger"
                aria-label={`delete project ${p.name}`}
                title="delete project"
                onClick={(e) => {
                  e.stopPropagation();
                  setOpen(false);
                  onDelete(p.id);
                }}
              >
                ×
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          className={`model-option new-project ${activeIndex === projects.length ? "kbd-active" : ""}`}
          onClick={() => {
            setOpen(false);
            onNew();
          }}
          onMouseEnter={() => setActiveIndex(projects.length)}
        >
          + new project
        </button>
      </div>
    ) : null;

  return (
    <div ref={ref} className={`model-picker project-picker ${open ? "open" : ""}`}>
      <button
        type="button"
        className="model-trigger project-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={current?.workspace ? `${current.name} — ${current.workspace}` : current?.name}
      >
        <span className="model-label">
          <span aria-hidden="true" style={{ marginRight: 6 }}>
            📁
          </span>
          {current?.name || "home"}
        </span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">
          ▾
        </span>
      </button>
      {menu && createPortal(menu, document.body)}
    </div>
  );
}

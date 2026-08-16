import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Props = {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  disabled?: boolean;
};

const LABELS: Record<string, string> = {
  auto: "auto",
  off: "off",
  low: "low",
  medium: "medium",
  high: "high",
  max: "max",
};

const DESCS: Record<string, string> = {
  auto: "let model decide",
  off: "no thinking",
  low: "quick think",
  medium: "balanced",
  high: "deep think",
  max: "max effort",
};

export function getReasoningOptions(model: string): string[] {
  const m = (model || "").toLowerCase();
  // thinking-capable families
  const isThinking =
    m.includes("qwen3") ||
    m.includes("qwq") ||
    m.includes("deepseek-r1") ||
    m.includes("deepseek") && m.includes("r1") ||
    m.includes("o1") ||
    m.includes("o3") ||
    m.includes("gpt-oss") ||
    m.includes("think");
  const isClaudeLike = m.includes("claude") || m.includes("sonnet") || m.includes("opus");
  const isGemma = m.includes("gemma") || m.includes("abliterated");

  if (isThinking) return ["auto", "off", "low", "medium", "high", "max"];
  if (isClaudeLike) return ["auto", "off", "low", "medium", "high"];
  if (isGemma) return ["auto", "off"];
  // generic fallback: assume thinking via prompt is possible
  return ["auto", "off", "low", "medium", "high"];
}

export default function ReasoningPicker({ value, options, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number | string; bottom: number | string; left: number; width: number; maxHeight: number } | null>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Element;
      if (ref.current?.contains(t)) return;
      if (t.closest?.(".model-menu")) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const estH = Math.min(280, options.length * 40 + 16);
    const spaceBelow = window.innerHeight - r.bottom;
    const spaceAbove = r.top;
    const below = spaceBelow > estH || spaceBelow > spaceAbove;
    const longest = Math.max(
      10,
      ...options.map((o) => `${LABELS[o] || o}  ${DESCS[o] || ""}`.length),
    );
    const width = Math.min(Math.max(176, longest * 7.2 + 44), 260, window.innerWidth - 24);
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    if (below) setPos({ top: r.bottom + 8, bottom: "auto", left, width, maxHeight: Math.max(120, window.innerHeight - r.bottom - 8) });
    else setPos({ top: "auto", bottom: window.innerHeight - r.top + 8, left, width, maxHeight: Math.max(120, r.top - 8) });
    const onScroll = (e: Event) => {
      const t = e.target as Element | null;
      if (t instanceof Element && t.closest(".model-menu")) return;
      setOpen(false);
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, options]);

  const cur = value || "auto";
  const menu =
    open && pos ? (
      <div
        className="model-menu reasoning-menu"
        role="listbox"
        style={{
          position: "fixed",
          left: pos.left,
          width: pos.width,
          minWidth: pos.width,
          maxWidth: pos.width,
          right: "auto",
          top: pos.top,
          bottom: pos.bottom,
          maxHeight: pos.maxHeight,
          zIndex: 9999,
          opacity: 1,
          transform: "none",
          pointerEvents: "auto",
        }}
      >
        {options.map((opt, i) => {
          const isActive = opt === cur;
          return (
            <button
              key={opt}
              role="option"
              aria-selected={isActive}
              className={`model-option ${isActive ? "active" : ""}`}
              style={{ ["--i" as any]: i } as any}
              onClick={() => {
                onChange(opt);
                setOpen(false);
              }}
            >
              <span className="model-name">{LABELS[opt] || opt}</span>
              <span className="mono" style={{ fontSize: 10, opacity: 0.6, marginLeft: 6 }}>
                {DESCS[opt] || ""}
              </span>
              {isActive && <span className="check">✓</span>}
            </button>
          );
        })}
      </div>
    ) : null;

  return (
    <div ref={ref} className={`model-picker ${open ? "open" : ""} ${disabled ? "disabled" : ""}`}>
      <button
        type="button"
        className="model-trigger"
        disabled={disabled}
        title={disabled ? "thinking not supported by this model" : `reasoning: ${LABELS[cur] || cur} — ${DESCS[cur] || ""}`}
        onClick={() => {
          if (disabled) return;
          setOpen((v) => !v);
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="mono" style={{ fontSize: 10, opacity: 0.7 }}>
          think
        </span>
        <span className="model-label">{LABELS[cur] || cur}</span>
        <span className={`chev ${open ? "up" : ""}`} aria-hidden="true">
          ▾
        </span>
      </button>
      {menu && createPortal(menu, document.body)}
    </div>
  );
}

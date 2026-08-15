import { useEffect } from "react";

export type Command = { name: string; desc: string; arg?: string; needChat?: boolean };

export const COMMANDS: Command[] = [
  { name: "help", desc: "show all commands" },
  { name: "new", desc: "start a new chat" },
  { name: "settings", desc: "open settings" },
  { name: "rename", desc: "rename this chat", arg: "title", needChat: true },
  { name: "pin", desc: "pin or unpin this chat", needChat: true },
  { name: "clear", desc: "clear all messages in this chat", needChat: true },
  { name: "export", desc: "copy this chat as markdown", needChat: true },
  { name: "model", desc: "switch worker model", arg: "name" },
  { name: "attach", desc: "attach files to this message" },
];

export function matchCommands(query: string, hasChat: boolean): Command[] {
  const q = query.trim().toLowerCase();
  const base = COMMANDS.filter((c) => !c.needChat || hasChat);
  if (!q) return base;
  return base.filter((c) => c.name.includes(q) || c.desc.toLowerCase().includes(q));
}

type MenuProps = {
  query: string;
  selected: number;
  hasChat: boolean;
  onHover: (i: number) => void;
};

export default function CommandMenu({ query, selected, hasChat, onHover }: MenuProps) {
  const list = matchCommands(query, hasChat);
  return (
    <div className="cmd-menu" role="menu">
      {list.length === 0 && <div className="cmd-none">no command matches “{query.trim()}”</div>}
      {list.map((c, i) => (
        <button
          type="button"
          role="menuitem"
          key={c.name}
          className={`cmd-item ${i === selected ? "sel" : ""}`}
          style={{ ["--i" as any]: i } as any}
          onMouseEnter={() => onHover(i)}
        >
          <span className="cmd-name">/{c.name}</span>
          {c.arg && <span className="cmd-arg">&lt;{c.arg}&gt;</span>}
          <span className="cmd-desc">{c.desc}</span>
        </button>
      ))}
      <div className="cmd-hint">↑↓ navigate · enter run · tab complete · esc dismiss</div>
    </div>
  );
}

export function HelpModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal help-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="commands">
        <h3>commands</h3>
        <div className="help-list">
          {COMMANDS.map((c) => (
            <div key={c.name} className="help-row">
              <span className="cmd-name">/{c.name}{c.arg ? ` <${c.arg}>` : ""}</span>
              <span className="cmd-desc">{c.desc}</span>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>close</button>
        </div>
      </div>
    </div>
  );
}

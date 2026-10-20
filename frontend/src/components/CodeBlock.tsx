import { useEffect, useState } from "react";

export default function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(async () => {
      // The highlighter (engine + theme + grammar) is its own chunk — a chat
      // with no code blocks never pays for it.
      const { highlight } = await import("../lib/highlight");
      const out = await highlight(code, lang || "");
      if (alive) setHtml(out);
    }, 200);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [code, lang]);

  return (
    <div className="code-block">
      <div className="code-head">
        <span className="mono">{lang?.trim() || "code"}</span>
        <button type="button" className="copy-btn" onClick={() => navigator.clipboard?.writeText(code)}>
          copy
        </button>
      </div>
      {html ? (
        <div className="code-body" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <pre>
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}

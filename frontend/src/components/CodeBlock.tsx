import { useEffect, useState } from "react";
import { codeToHtml } from "shiki";

const THEME = "dark-plus";
const FALLBACK_LANG = "plaintext";

codeToHtml("", { lang: FALLBACK_LANG, theme: THEME }).catch(() => {});

export default function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(async () => {
      try {
        const langKey = (lang || "").trim().toLowerCase();
        const h = await codeToHtml(code, { lang: langKey || FALLBACK_LANG, theme: THEME });
        if (alive) setHtml(h);
      } catch {
        if (alive) setHtml(null);
      }
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

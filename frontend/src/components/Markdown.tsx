import { useMemo } from "react";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="mono">code</span>
        <button type="button" className="copy-btn" onClick={() => navigator.clipboard?.writeText(code)}>
          copy
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

export default function Markdown({ text }: { text: string }) {
  // Split on code fences ourselves so code blocks get chrome + copy button;
  // everything else flows through marked.
  const parts = useMemo(() => {
    const out: { kind: "md" | "code"; text: string }[] = [];
    const re = /```(\w*)\n([\s\S]*?)(?:```|$)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text || ""))) {
      if (m.index > last) out.push({ kind: "md", text: text.slice(last, m.index) });
      out.push({ kind: "code", text: m[2] });
      last = m.index + m[0].length;
    }
    if (last < (text || "").length) out.push({ kind: "md", text: text.slice(last) });
    return out;
  }, [text]);

  return (
    <div className="md">
      {parts.map((p, i) =>
        p.kind === "code" ? (
          <CodeBlock key={i} code={p.text} />
        ) : (
          <div key={i} dangerouslySetInnerHTML={{ __html: marked.parse(p.text) as string }} />
        ),
      )}
    </div>
  );
}

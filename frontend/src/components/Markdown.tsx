import { useMemo } from "react";
import { marked } from "marked";
import CodeBlock from "./CodeBlock";

marked.setOptions({ breaks: true, gfm: true });

const ALLOWED_TAGS = new Set([
  "A", "B", "STRONG", "EM", "I", "U", "S", "DEL", "CODE", "PRE", "P", "BR",
  "UL", "OL", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "HR",
  "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "SPAN", "DIV", "IMG", "SUP", "SUB", "INPUT",
]);

function sanitizeHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const els = Array.from(doc.body.querySelectorAll("*"));
  for (const el of els) {
    if (!ALLOWED_TAGS.has(el.tagName)) {
      el.replaceWith(...Array.from(el.childNodes));
      continue;
    }
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
        continue;
      }
      if (name === "href" || name === "src") {
        // browsers strip ASCII tab/LF/CR before scheme detection — do the same
        const v = attr.value.trim().replace(/[\t\n\r]/g, "");
        if (/^\s*(javascript|data|vbscript):/i.test(v)) {
          el.removeAttribute(attr.name);
        }
      }
    }
    if (el.tagName === "A") {
      el.setAttribute("rel", "noopener noreferrer");
      el.setAttribute("target", "_blank");
    }
    if (el.tagName === "INPUT") {
      el.setAttribute("disabled", "");
      el.setAttribute("type", "checkbox");
    }
  }
  return doc.body.innerHTML;
}

export default function Markdown({ text }: { text: string }) {
  const parts = useMemo(() => {
    const out: { kind: "md" | "code"; text: string; lang: string }[] = [];
    const re = /```([^\s`]*)\n?([\s\S]*?)(?:```|$)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text || ""))) {
      if (m.index > last) out.push({ kind: "md", text: text.slice(last, m.index), lang: "" });
      out.push({ kind: "code", text: m[2], lang: m[1] || "" });
      last = m.index + m[0].length;
    }
    if (last < (text || "").length) out.push({ kind: "md", text: text.slice(last), lang: "" });
    return out;
  }, [text]);

  return (
    <div className="md">
      {parts.map((p, i) =>
        p.kind === "code" ? (
          <CodeBlock key={i} code={p.text} lang={p.lang} />
        ) : (
          <div key={i} dangerouslySetInnerHTML={{ __html: sanitizeHtml(marked.parse(p.text) as string) }} />
        ),
      )}
    </div>
  );
}

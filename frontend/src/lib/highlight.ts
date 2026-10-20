/**
 * Syntax highlighting, kept deliberately small.
 *
 * The full `shiki` bundle ships 360 grammars and 65 themes — ~9.9 MB of
 * build output for a chat UI that realistically renders a dozen languages.
 * This module uses `shiki/core` with the pure-JS regex engine (no WASM) and
 * loads a grammar on demand, so a page only downloads the languages it
 * actually shows.
 */

import { createHighlighterCore, type HighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

const THEME = "dark-plus";

/** Curated grammars. Each becomes its own lazy chunk. */
const GRAMMARS: Record<string, () => Promise<unknown>> = {
  python: () => import("shiki/langs/python.mjs"),
  javascript: () => import("shiki/langs/javascript.mjs"),
  typescript: () => import("shiki/langs/typescript.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  json: () => import("shiki/langs/json.mjs"),
  yaml: () => import("shiki/langs/yaml.mjs"),
  toml: () => import("shiki/langs/toml.mjs"),
  bash: () => import("shiki/langs/bash.mjs"),
  html: () => import("shiki/langs/html.mjs"),
  css: () => import("shiki/langs/css.mjs"),
  markdown: () => import("shiki/langs/markdown.mjs"),
  sql: () => import("shiki/langs/sql.mjs"),
  go: () => import("shiki/langs/go.mjs"),
  rust: () => import("shiki/langs/rust.mjs"),
  java: () => import("shiki/langs/java.mjs"),
  c: () => import("shiki/langs/c.mjs"),
  cpp: () => import("shiki/langs/cpp.mjs"),
  csharp: () => import("shiki/langs/csharp.mjs"),
  php: () => import("shiki/langs/php.mjs"),
  ruby: () => import("shiki/langs/ruby.mjs"),
  lua: () => import("shiki/langs/lua.mjs"),
  kotlin: () => import("shiki/langs/kotlin.mjs"),
  swift: () => import("shiki/langs/swift.mjs"),
  xml: () => import("shiki/langs/xml.mjs"),
  diff: () => import("shiki/langs/diff.mjs"),
  dockerfile: () => import("shiki/langs/dockerfile.mjs"),
  powershell: () => import("shiki/langs/powershell.mjs"),
};

/** Aliases people actually type in a fence. */
const ALIASES: Record<string, string> = {
  js: "javascript",
  ts: "typescript",
  py: "python",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  yml: "yaml",
  md: "markdown",
  "c++": "cpp",
  "c#": "csharp",
  cs: "csharp",
  rs: "rust",
  kt: "kotlin",
  ps1: "powershell",
  docker: "dockerfile",
  golang: "go",
  htm: "html",
  scss: "css",
  plaintext: "",
  text: "",
  txt: "",
  plain: "",
};

export function normalizeLang(lang: string): string {
  const key = (lang || "").trim().toLowerCase();
  if (!key) return "";
  const mapped = ALIASES[key] ?? key;
  return mapped in GRAMMARS ? mapped : "";
}

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

let highlighterPromise: Promise<HighlighterCore> | null = null;
const loading = new Map<string, Promise<void>>();

async function getHighlighter(): Promise<HighlighterCore> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighterCore({
      themes: [import("shiki/themes/dark-plus.mjs")],
      langs: [],
      engine: createJavaScriptRegexEngine(),
    });
  }
  return highlighterPromise;
}

async function ensureLang(hl: HighlighterCore, lang: string): Promise<void> {
  if (hl.getLoadedLanguages().includes(lang)) return;
  const pending = loading.get(lang);
  if (pending) return pending;
  const task = (async () => {
    const mod = (await GRAMMARS[lang]()) as { default: unknown };
    await hl.loadLanguage(mod.default as never);
    loading.delete(lang);
  })();
  loading.set(lang, task);
  return task;
}

/**
 * Highlight a snippet. Returns plain (escaped) HTML when the language is
 * unknown or the grammar fails to load — never throws.
 */
export async function highlight(code: string, lang: string): Promise<string> {
  const name = normalizeLang(lang);
  if (!name) return `<pre><code>${escapeHtml(code)}</code></pre>`;
  try {
    const hl = await getHighlighter();
    await ensureLang(hl, name);
    return hl.codeToHtml(code, { lang: name, theme: THEME });
  } catch {
    return `<pre><code>${escapeHtml(code)}</code></pre>`;
  }
}

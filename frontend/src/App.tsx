import { useEffect, useMemo, useRef, useState } from "react";
import Iridescence from "./components/Iridescence";
import CommandMenu, { HelpModal, matchCommands, type Command } from "./components/CommandMenu";
import Confirm from "./components/Confirm";
import Markdown from "./components/Markdown";
import Modal from "./components/Modal";
import ModelPicker from "./components/ModelPicker";
import ProjectPicker from "./components/ProjectPicker";
import ReasoningPicker, { getReasoningOptions } from "./components/ReasoningPicker";
import type {
  AgentSnapshot,
  Attachment,
  Chat,
  IronEvent,
  McpServer,
  Message,
  Project,
  RunSnapshot,
  Settings,
  Trace,
  Usage,
} from "./types";

const SUGGESTIONS = [
  { label: "hello world", goal: "Create a tiny hello_world.py that prints iron, then run it." },
  { label: "map this workspace", goal: "Inspect the workspace, list the important files, and write a short architecture note." },
  { label: "split a real task", goal: "Create two small Python modules (math_utils.py and string_utils.py) with one function each, plus a README explaining them." },
];

let apiToken = "";

async function fetchToken() {
  try {
    const res = await fetch("/api/bootstrap");
    if (!res.ok) return;
    const data = (await res.json()) as { token?: string };
    if (data.token) apiToken = data.token;
  } catch {
    /* old backend without tokens — requests proceed without a header */
  }
}

const api = {
  async json<T>(path: string, init?: RequestInit): Promise<T> {
    if (!apiToken) await fetchToken();
    const headers = {
      "Content-Type": "application/json",
      ...(apiToken ? { "X-Iron-Token": apiToken } : {}),
      ...(init?.headers || {}),
    };
    const res = await fetch(path, { ...init, headers });
    if (res.status === 403 && apiToken) {
      // server restarted with a fresh token — re-fetch and retry once
      await fetchToken();
      if (apiToken) {
        const retry = await fetch(path, { ...init, headers: { ...headers, "X-Iron-Token": apiToken } });
        if (!retry.ok) throw new Error(`request failed (${retry.status})`);
        return retry.json() as Promise<T>;
      }
    }
    if (!res.ok) throw new Error(`request failed (${res.status})`);
    return res.json() as Promise<T>;
  },
};

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function fmtTime(ms: number) {
  if (!ms) return "";
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtDay(ms: number) {
  if (!ms) return "";
  const d = new Date(ms);
  const now = new Date();
  const same = d.toDateString() === now.toDateString();
  if (same) return fmtTime(ms);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function prettySize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function shortPath(path: string, keep = 2): string {
  if (!path) return "";
  const p = path.replace(/\\/g, "/");
  const parts = p.split("/").filter(Boolean);
  if (parts.length <= keep) return path;
  return "…/" + parts.slice(-keep).join("/");
}

function fmtTok(n: number) {
  if (!n) return "0";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function ctxPct(u?: Usage) {
  if (!u || !u.ctx) return 0;
  return Math.min(100, Math.round((u.prompt / u.ctx) * 100));
}

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [modelError, setModelError] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<"chat" | "settings">("chat");
  const [showNewProject, setShowNewProject] = useState(false);
  const [toast, setToast] = useState("");
  const [editingMsg, setEditingMsg] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<{ chatId?: string; projectId?: string; messageId?: string } | null>(null);
  const [cmdSelected, setCmdSelected] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpTesting, setMcpTesting] = useState("");
  const [mcpForm, setMcpForm] = useState({ name: "", type: "stdio", command: "", args: "", url: "" });
  const [projectFiles, setProjectFiles] = useState<{ name: string; is_dir: boolean; size: number; modified: number }[]>([]);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const [orchText, setOrchText] = useState<Record<string, string>>({});
  const [orchThink, setOrchThink] = useState<Record<string, string>>({});
  const [plans, setPlans] = useState<Record<string, { title: string; goal: string }[]>>({});
  const [traces, setTraces] = useState<Record<string, Trace[]>>({});
  const [agents, setAgents] = useState<Record<string, AgentSnapshot[]>>({});
  const [asks, setAsks] = useState<Record<string, string>>({});
  const [runs, setRuns] = useState<Record<string, RunSnapshot>>({});
  const [usage, setUsage] = useState<Record<string, Usage>>({});
  const [agentUsage, setAgentUsage] = useState<Record<string, Usage>>({});
  const streamRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const projectIdRef = useRef(projectId);
  useEffect(() => {
    projectIdRef.current = projectId;
  }, [projectId]);

  const project = projects.find((p) => p.id === projectId) || null;
  const chat = chats.find((c) => c.id === chatId) || null;
  const visibleChats = useMemo(() => {
    const q = query.trim().toLowerCase();
    return chats
      .filter((c) => c.project_id === projectId)
      .filter((c) => c.messages.length > 0 || c.pinned || c.id === chatId)
      .filter((c) => !q || c.title.toLowerCase().includes(q) || c.messages.some((m) => m.content.toLowerCase().includes(q)))
      .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updated_at - a.updated_at);
  }, [chats, projectId, query, chatId]);

  const lastRunId = [...(chat?.messages || [])].reverse().find((m) => m.run_id)?.run_id || "";
  const activeRun = lastRunId ? runs[lastRunId] : null;
  const activeAgents = activeRun ? agents[activeRun.id] || activeRun.agents || [] : [];
  const running = activeAgents.filter((a) => !["done", "failed", "cancelled"].includes(a.status)).length;
  const cmdOpen = goal.startsWith("/");
  const cmdList = cmdOpen ? matchCommands(goal.slice(1), !!chat) : [];
  const cmdIdx = Math.min(cmdSelected, Math.max(0, cmdList.length - 1));
  const runActive = !!activeRun && ["running", "queued", "needs_input"].includes(activeRun.status);
  const lastAssistant = chat?.messages.filter((m) => m.role === "assistant").reverse()[0];
  const gaugeUsage: Usage | undefined = (lastRunId ? usage[lastRunId] : undefined) || activeRun?.usage || lastAssistant?.usage;
  const gaugePct = ctxPct(gaugeUsage);
  const goalEst = Math.round((goal.trim().length || 0) / 3.2);
  const goalHot = goalEst > (settings?.num_ctx || 65536) * 0.6;

  useEffect(() => {
    (async () => {
      try {
        const s = await api.json<Settings>("/api/settings");
        setSettings(s);
        await loadModels(3);
        const p = await api.json<{ projects: Project[]; active_project_id?: string }>("/api/projects");
        setProjects(p.projects || []);
        const pid = p.active_project_id || p.projects?.[0]?.id || "";
        setProjectId(pid);
        if (pid) {
          const c = await api.json<{ chats: Chat[] }>(`/api/chats?project_id=${pid}`);
          setChats(c.chats || []);
        }
        const r = await api.json<{ runs: RunSnapshot[] }>("/api/runs");
        setRuns((prev) => {
          const next = { ...prev };
          for (const run of r.runs || []) next[run.id] = { ...(next[run.id] || {}), ...run };
          return next;
        });
      } catch {
        /* backend not ready — ws + watchdog will recover */
      }
    })();
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;
    const connect = () => {
      if (!apiToken) void fetchToken();
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(apiToken)}`);
      ws.onopen = () => {
        setLive(true);
        loadModels(1);
        resync();
      };
      ws.onclose = () => {
        setLive(false);
        if (!stopped) timer = window.setTimeout(connect, 1200);
      };
      ws.onerror = () => setLive(false);
      ws.onmessage = (ev) => {
        try {
          handleEvent(JSON.parse(ev.data) as IronEvent);
        } catch {
          /* ignore */
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight });
  }, [chatId, chat?.messages, orchText, asks, traces]);

  useEffect(() => {
    let stopped = false;
    (async () => {
      for (let tries = 0; tries < 12 && !stopped; tries++) {
        if (models.length > 0) break;
        const names = await loadModels(0);
        if (names.length > 0 || stopped) break;
        await new Promise((r) => window.setTimeout(r, 2500));
      }
    })();
    return () => { stopped = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "c") return;
      const target = e.target as HTMLElement | null;
      const editable = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (editable && !e.shiftKey) {
        const el = target as HTMLInputElement;
        const selected = "selectionStart" in el ? el.selectionStart !== el.selectionEnd : !!window.getSelection()?.toString();
        if (selected) return; // preserve copy in text fields
      }
      if (!activeRun || !["running", "needs_input", "queued"].includes(activeRun.status)) return;
      e.preventDefault();
      cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeRun]);

  useEffect(() => {
    const save = () => {
      const w = window.outerWidth;
      const h = window.outerHeight;
      if (!w || !h) return;
      const x = window.screenX;
      const y = window.screenY;
      api.json("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ window_w: w, window_h: h, window_x: x, window_y: y }),
      }).catch(() => { /* offline — geometry persists next launch */ });
    };
    let timer: number | undefined;
    const onResize = () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(save, 800);
    };
    const onHide = () => save();
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onHide);
    save();
    return () => {
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onHide);
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (page === "settings") loadMcpServers();
  }, [page]);

  useEffect(() => {
    if (!settings) return;
    const opts = getReasoningOptions(settings.model || "");
    const cur = settings.reasoning_level || "auto";
    if (!opts.includes(cur)) saveSettings({ reasoning_level: "auto" });
  }, [settings?.model]);

  async function refreshChats(pid = projectId) {
    if (!pid) return;
    try {
      const c = await api.json<{ chats: Chat[] }>(`/api/chats?project_id=${pid}`);
      setChats(c.chats || []);
    } catch {
      /* backend not ready */
    }
  }

  async function loadProjectFiles(pid = projectId) {
    if (!pid) {
      setProjectFiles([]);
      return;
    }
    try {
      const res = await api.json<{ files: { name: string; is_dir: boolean; size: number; modified: number }[]; workspace: string }>(`/api/projects/${pid}/files`);
      setProjectFiles(res.files || []);
    } catch {
      setProjectFiles([]);
    }
  }

  async function revealProject(pid: string) {
    try {
      await api.json(`/api/projects/${pid}/reveal`, { method: "POST" });
      flash("opened in file explorer");
    } catch {
      flash("couldn't open folder");
    }
  }

  async function resync() {
    try {
      if (!settings) {
        const s = await api.json<Settings>("/api/settings");
        setSettings(s);
      }
      if (projects.length === 0) {
        const p = await api.json<{ projects: Project[]; active_project_id?: string }>("/api/projects");
        setProjects(p.projects || []);
        const pid = p.active_project_id || p.projects?.[0]?.id || "";
        if (!projectIdRef.current && pid) setProjectId(pid);
      }
      const r = await api.json<{ runs: RunSnapshot[] }>("/api/runs");
      setRuns((prev) => {
        const next = { ...prev };
        for (const run of r.runs || []) next[run.id] = { ...(next[run.id] || {}), ...run };
        return next;
      });
      const active = (r.runs || []).some((x) => ["running", "queued", "needs_input"].includes(x.status));
      if (!active) setBusy(false);
      if (projectIdRef.current) await refreshChats(projectIdRef.current);
    } catch {
      /* backend still warming up */
    }
  }

  async function loadModels(retries = 0) {
    for (let i = 0; i <= retries; i++) {
      try {
        const m = await api.json<{ models: { name: string }[]; error?: string }>("/api/models");
        const names = (m.models || []).map((x) => x.name);
        if (names.length > 0) {
          setModels(names);
          setModelError(m.error || "");
          return names;
        }
        setModelError(m.error || "no models found — is ollama running?");
      } catch {
        setModelError("can't reach ollama");
      }
      if (i < retries) await new Promise((r) => window.setTimeout(r, 1500));
    }
    return [];
  }

  async function switchProject(id: string) {
    setProjectId(id);
    setChatId(null);
    setPage("chat");
    setEditingMsg(null);
    setRenaming(false);
    setFiles([]);
    await refreshChats(id);
    await loadProjectFiles(id);
  }

  useEffect(() => {
    if (projectId) loadProjectFiles(projectId);
    else setProjectFiles([]);
  }, [projectId]);

  function upsertRun(next: Partial<RunSnapshot> & { id: string }) {
    setRuns((prev) => ({ ...prev, [next.id]: { ...(prev[next.id] || { agents: [] }), ...next } as RunSnapshot }));
  }

  function upsertAgent(runId: string, agent: AgentSnapshot) {
    setAgents((prev) => {
      const list = prev[runId] ? [...prev[runId]] : [];
      const i = list.findIndex((a) => a.id === agent.id);
      if (i < 0) list.push(agent);
      else list[i] = { ...list[i], ...agent };
      return { ...prev, [runId]: list };
    });
    setRuns((prev) => {
      const run = prev[runId];
      if (!run) return prev;
      const list = [...(run.agents || [])];
      const i = list.findIndex((a) => a.id === agent.id);
      if (i < 0) list.push(agent);
      else list[i] = { ...list[i], ...agent };
      return { ...prev, [runId]: { ...run, agents: list } };
    });
  }

  function pushTrace(agentId: string, kind: Trace["kind"], text: string, extra?: Partial<Trace>) {
    if (!text && kind !== "status") return;
    setTraces((prev) => {
      const list = prev[agentId] ? [...prev[agentId]] : [];
      const last = list[list.length - 1];
      if (last && last.kind === kind && (kind === "think" || kind === "token")) {
        list[list.length - 1] = { ...last, text: last.text + text };
        return { ...prev, [agentId]: list };
      }
      list.push({ id: uid(), ts: Date.now(), agentId, kind, text, ...extra });
      return { ...prev, [agentId]: list.slice(-80) };
    });
  }

  function patchAssistant(runId: string, content: string, status?: string) {
    setChats((prev) =>
      prev.map((c) => ({
        ...c,
        messages: c.messages.map((m) => (m.run_id === runId && m.role === "assistant" ? { ...m, content, status } : m)),
      })),
    );
  }

  function handleEvent(event: IronEvent) {
    if (event.type === "hello") return;
    const runId = event.run_id;
    if (event.run && event.run.id) upsertRun(event.run);
    if (event.agent && runId) upsertAgent(runId, event.agent);
    if (event.type === "run.status" && runId) {
      upsertRun({ id: runId, status: (event.status as RunSnapshot["status"]) || "running" });
      if (event.status === "done" || event.status === "failed" || event.status === "cancelled") setBusy(false);
    }
    if (event.type === "run.token" && runId && event.text) {
      setOrchText((p) => ({ ...p, [runId]: (p[runId] || "") + event.text }));
    }
    if (event.type === "run.think" && runId && event.text) {
      setOrchThink((p) => ({ ...p, [runId]: (p[runId] || "") + event.text }));
    }
    if (event.type === "run.plan" && runId && event.tasks) {
      setPlans((p) => ({ ...p, [runId]: event.tasks || [] }));
    }
    if (event.type === "run.result" && runId) {
      upsertRun({ id: runId, result: event.result || "", status: "done" });
      patchAssistant(runId, event.result || "", "done");
      setBusy(false);
    }
    if (event.type === "run.error" && runId) {
      upsertRun({ id: runId, error: event.error || "", status: "failed" });
      patchAssistant(runId, event.error || "", "failed");
      setBusy(false);
    }
    if (event.type === "run.ask" && runId) setAsks((p) => ({ ...p, [runId]: event.question || "Need input" }));
    if (event.type === "run.usage" && runId && event.num_ctx) {
      setUsage((prev) => {
        const cur = prev[runId];
        const prompt = Math.max(cur?.prompt || 0, event.prompt_tokens || 0);
        return { ...prev, [runId]: { prompt, ctx: event.num_ctx || cur?.ctx || 0 } };
      });
    }
    if (event.type === "agent.usage" && event.agent_id && event.num_ctx) {
      setAgentUsage((prev) => {
        const cur = prev[event.agent_id!];
        const prompt = Math.max(cur?.prompt || 0, event.prompt_tokens || 0);
        return { ...prev, [event.agent_id!]: { prompt, ctx: event.num_ctx || cur?.ctx || 0 } };
      });
    }
    if (event.type === "agent.spawn" && event.agent && runId) upsertAgent(runId, event.agent);
    if (event.type === "agent.status" && event.agent && runId) upsertAgent(runId, event.agent);
    if (event.agent_id && event.type === "agent.think") pushTrace(event.agent_id, "think", event.text || "");
    if (event.agent_id && event.type === "agent.token") pushTrace(event.agent_id, "token", event.text || "");
    if (event.agent_id && event.type === "agent.tool") {
      const label =
        event.phase === "end"
          ? `${event.tool} → ${(event.result || "").slice(0, 240)}`
          : `${event.tool}(${JSON.stringify(event.args || {}).slice(0, 160)})`;
      pushTrace(event.agent_id, "tool", label, { tool: event.tool, phase: event.phase });
    }
    if (event.agent_id && event.type === "agent.result") pushTrace(event.agent_id, "result", event.result || "");
    if (event.agent_id && event.type === "agent.error") pushTrace(event.agent_id, "error", event.error || "");
  }

  async function newChat() {
    setChatId(null);
    setPage("chat");
    setGoal("");
    setFiles([]);
    boxRef.current?.focus();
  }

  async function newProject(name: string) {
    if (!name.trim()) return;
    try {
      const item = await api.json<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name, workspace: "" }),
      });
      if ((item as unknown as { error?: string }).error) return;
      setProjects((prev) => [...prev, item]);
      await switchProject(item.id);
    } catch {
      flash("couldn't create project");
    }
  }

  async function deleteProject(id: string) {
    if (projects.length <= 1) return;
    setConfirmDelete({ projectId: id });
  }

  async function confirmDeleteProject() {
    const id = confirmDelete?.projectId;
    if (!id) {
      setConfirmDelete(null);
      return;
    }
    let ok = false;
    try {
      const res = await api.json<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" });
      ok = !!res.ok;
    } catch {
      flash("couldn't delete project");
    }
    setConfirmDelete(null);
    if (!ok) return;
    const remaining = projects.filter((p) => p.id !== id);
    setProjects(remaining);
    if (projectId === id) {
      const next = remaining[0];
      if (next) await switchProject(next.id);
      else setChatId(null);
    } else {
      await refreshChats(projectId);
    }
    flash("project deleted");
  }

  async function launch(text = goal, attachments: Attachment[] = files) {
    const next = text.trim();
    if (!next || busy || runActive || !projectId) return;
    setBusy(true);
    try {
      const run = await api.json<RunSnapshot & { chat?: Chat }>("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          goal: next,
          workspace: project?.workspace || settings?.workspace,
          model: settings?.model || undefined,
          project_id: projectId,
          chat_id: chatId,
          attachments,
        }),
      });
      if ((run as unknown as { error?: string }).error) {
        flash("couldn't start run");
        setBusy(false);
        return;
      }
      upsertRun(run);
      if (run.chat) {
        setChats((prev) => {
          const rest = prev.filter((c) => c.id !== run.chat!.id);
          return [run.chat!, ...rest];
        });
        setChatId(run.chat.id);
      }
      setGoal("");
      setFiles([]);
      setOrchText((p) => ({ ...p, [run.id]: "" }));
    } catch {
      flash("backend unreachable — retrying…");
      setBusy(false);
    }
  }

  async function cancel() {
    if (!activeRun) return;
    try {
      await api.json(`/api/runs/${activeRun.id}/cancel`, { method: "POST" });
    } catch {
      flash("backend unreachable");
      return;
    }
    setBusy(false);
  }

  async function reply() {
    if (!activeRun || !input.trim()) return;
    const text = input.trim();
    try {
      await api.json(`/api/runs/${activeRun.id}/input`, { method: "POST", body: JSON.stringify({ text }) });
    } catch {
      flash("backend unreachable");
      return;
    }
    if (chatId) {
      setChats((prev) =>
        prev.map((c) =>
          c.id === chatId
            ? { ...c, messages: [...c.messages, { id: uid(), role: "user" as const, content: text, attachments: [], ts: Date.now() }] }
            : c,
        ),
      );
    }
    setAsks((p) => ({ ...p, [activeRun.id]: "" }));
    setInput("");
  }

  async function saveSettings(patch: Partial<Settings>) {
    if (!settings) return;
    try {
      const next = await api.json<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) });
      setSettings(next);
    } catch {
      flash("couldn't save settings");
    }
  }

  async function loadMcpServers() {
    try {
      const res = await api.json<{ servers: McpServer[] }>("/api/mcp/servers");
      setMcpServers(res.servers);
    } catch {
      /* settings page may open before backend is ready */
    }
  }

  async function addMcpServer() {
    const config: Record<string, string> = { type: mcpForm.type };
    if (mcpForm.type === "stdio") {
      config.command = mcpForm.command.trim();
      config.args = mcpForm.args;
    } else {
      config.url = mcpForm.url.trim();
    }
    const name = mcpForm.name.trim();
    if (!name) {
      flash("give the server a name");
      return;
    }
    try {
      const res = await api.json<{ ok: boolean; error?: string; servers?: McpServer[] }>("/api/mcp/servers", {
        method: "POST",
        body: JSON.stringify({ name, config }),
      });
      if (!res.ok) {
        flash(res.error || "couldn't add server");
        return;
      }
      setMcpServers(res.servers || []);
      setMcpForm({ name: "", type: "stdio", command: "", args: "", url: "" });
      flash("mcp server added");
    } catch {
      flash("couldn't add server");
    }
  }

  async function removeMcpServer(name: string) {
    try {
      const res = await api.json<{ ok: boolean; servers?: McpServer[] }>(`/api/mcp/servers/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (res.ok) setMcpServers(res.servers || []);
    } catch {
      flash("couldn't remove server");
    }
  }

  async function testMcpServer(name: string) {
    setMcpTesting(name);
    try {
      const res = await api.json<{ ok: boolean; error?: string; tools?: string[] }>(
        `/api/mcp/servers/${encodeURIComponent(name)}/test`,
        { method: "POST" },
      );
      if (res.ok) flash(`${name}: ${res.tools?.length || 0} tools`);
      else flash(`${name}: ${res.error || "connection failed"}`);
    } catch {
      flash(`${name}: connection failed`);
    }
    setMcpTesting("");
    loadMcpServers();
  }

  async function saveProjectWorkspace(workspace: string) {
    if (!project) return;
    try {
      const next = await api.json<Project>(`/api/projects/${project.id}`, {
        method: "PUT",
        body: JSON.stringify({ name: project.name, workspace }),
      });
      setProjects((prev) => prev.map((p) => (p.id === next.id ? next : p)));
    } catch {
      /* debounced keystroke — ignore transient failures */
    }
  }

  async function removeChat(id: string) {
    try {
      await api.json(`/api/chats/${id}`, { method: "DELETE" });
    } catch {
      flash("couldn't delete chat");
      return;
    }
    setChats((prev) => prev.filter((c) => c.id !== id));
    if (chatId === id) setChatId(null);
  }

  async function deleteMessage(id: string) {
    if (!chatId) return;
    try {
      const res = await api.json<{ ok: boolean; chat?: Chat }>(`/api/chats/${chatId}/messages/${id}`, { method: "DELETE" });
      if (res.ok) {
        setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, messages: c.messages.filter((m) => m.id !== id) } : c)));
        flash("message deleted");
      }
    } catch {
      flash("couldn't delete message");
    }
    setConfirmDelete(null);
  }

  async function saveEdit(id: string): Promise<boolean> {
    if (!chatId) return false;
    const content = editText.trim();
    if (!content) return false;
    try {
      const res = await api.json<{ ok: boolean; chat?: Chat }>(`/api/chats/${chatId}/messages/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ content }),
      });
      if (res.ok && res.chat) {
        setChats((prev) => prev.map((c) => (c.id === chatId ? res.chat! : c)));
        setEditingMsg(null);
        flash("message updated");
        return true;
      }
    } catch {
      flash("couldn't save edit");
    }
    return false;
  }

  function flash(text: string) {
    setToast(text);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1800);
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      flash("copied");
    } catch {
      /* clipboard may be blocked */
    }
  }

  async function regenerate() {
    if (!chat) return;
    const lastUser = [...chat.messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    await launch(lastUser.content, lastUser.attachments || []);
  }

  async function resendEdited(id: string) {
    const content = editText.trim();
    if (!content) return;
    const ok = await saveEdit(id);
    if (!ok) return;
    const msg = chat?.messages.find((m) => m.id === id);
    await launch(content, msg?.attachments || []);
  }

  async function renameChat(title: string) {
    if (!chatId) return;
    const nextTitle = title.trim();
    if (!nextTitle) return;
    try {
      const next = await api.json<Chat>(`/api/chats/${chatId}`, { method: "PATCH", body: JSON.stringify({ title: nextTitle }) });
      setChats((prev) => prev.map((c) => (c.id === next.id ? { ...c, ...next } : c)));
    } catch {
      flash("couldn't rename");
    }
    setRenaming(false);
  }

  async function clearChat() {
    if (!chatId) return;
    const res = await api.json<{ ok: boolean; chat?: Chat }>(`/api/chats/${chatId}/clear`, { method: "POST" });
    if (res.ok && res.chat) {
      setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, messages: [] } : c)));
      flash("chat cleared");
    }
    setConfirmClear(false);
  }

  function exportChat() {
    if (!chat) return;
    const lines = [`# ${chat.title || "chat"}`, ""];
    for (const m of chat.messages) {
      if (m.role === "user") {
        lines.push("**user:**", m.content, "");
        for (const f of m.attachments || []) lines.push(`*(attached: ${f.name})*`);
      } else if (m.role === "assistant" && m.content) {
        lines.push("**iron:**", m.content, "");
      }
    }
    copyText(lines.join("\n"));
    flash("chat copied as markdown");
  }

  function runCommand(cmd: Command, raw: string) {
    const parts = raw.trim().split(/\s+/);
    const arg = parts.slice(1).join(" ").trim();
    setGoal("");
    setCmdSelected(0);
    switch (cmd.name) {
      case "help":
        setHelpOpen(true);
        break;
      case "new":
        newChat();
        break;
      case "settings":
        setPage("settings");
        break;
      case "rename":
        if (arg && chatId) renameChat(arg);
        else setRenaming(true);
        break;
      case "pin":
        if (chat) pinChat(chat);
        break;
      case "clear":
        setConfirmClear(true);
        break;
      case "export":
        exportChat();
        break;
      case "model":
        if (arg) saveSettings({ model: arg });
        else flash("models: " + (models.length ? models.join(", ") : "none"));
        break;
      case "attach":
        fileRef.current?.click();
        break;
    }
  }

  async function pinChat(c: Chat) {
    try {
      const next = await api.json<Chat>(`/api/chats/${c.id}`, {
        method: "PATCH",
        body: JSON.stringify({ pinned: !c.pinned }),
      });
      setChats((prev) => prev.map((x) => (x.id === next.id ? { ...x, ...next } : x)));
    } catch {
      flash("couldn't update chat");
    }
  }

  async function onPickFiles(list: FileList | null) {
    if (!list || !list.length) return;
    let id = chatId;
    if (!id) {
      if (!projectId) return;
      try {
        const created = await api.json<Chat>("/api/chats", {
          method: "POST",
          body: JSON.stringify({ project_id: projectId, title: "New chat" }),
        });
        id = created.id;
        setChats((prev) => [created, ...prev]);
        setChatId(id);
      } catch {
        flash("couldn't create chat");
        return;
      }
    }
    const uploaded: Attachment[] = [];
    try {
      for (const file of Array.from(list)) {
        const body = new FormData();
        body.append("file", file);
        const res = await fetch(`/api/chats/${id}/upload`, {
          method: "POST",
          body,
          headers: apiToken ? { "X-Iron-Token": apiToken } : undefined,
        });
        if (!res.ok) throw new Error(`upload failed (${res.status})`);
        const data = (await res.json()) as Attachment & { error?: string };
        if (data.error) throw new Error(data.error);
        uploaded.push({ name: data.name, path: data.path, size: data.size });
      }
    } catch {
      flash("upload failed");
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
    setFiles((prev) => [...prev, ...uploaded]);
  }

  const composer = (
    <div className="composer">
      {files.length > 0 && (
        <div className="attach-list">
          {files.map((f) => (
            <span key={f.path} className="attach">
              {f.name}
              <em>{prettySize(f.size)}</em>
              <button type="button" aria-label={`remove ${f.name}`} onClick={() => setFiles((prev) => prev.filter((x) => x.path !== f.path))}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {cmdOpen && (
        <CommandMenu query={goal.slice(1)} selected={cmdIdx} hasChat={!!chat} onHover={setCmdSelected} />
      )}
      <textarea
        ref={boxRef}
        value={goal}
        placeholder={chat ? "message iron… (/ for commands)" : "what should iron do? (/ for commands)"}
        onChange={(e) => { setGoal(e.target.value); setCmdSelected(0); }}
        onKeyDown={(e) => {
          if (cmdOpen && cmdList.length > 0) {
            if (e.key === "ArrowDown") { e.preventDefault(); setCmdSelected((s) => (s + 1) % cmdList.length); return; }
            if (e.key === "ArrowUp") { e.preventDefault(); setCmdSelected((s) => (s - 1 + cmdList.length) % cmdList.length); return; }
            if (e.key === "Tab") { e.preventDefault(); setGoal("/" + cmdList[cmdIdx].name + " "); setCmdSelected(0); return; }
            if (e.key === "Enter") { e.preventDefault(); runCommand(cmdList[cmdIdx], goal.slice(1)); return; }
            if (e.key === "Escape") { e.preventDefault(); setGoal(""); return; }
          }
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            launch();
          }
        }}
      />
      <div className="row">
        <div className="meta">
          <button className="icon-btn" type="button" aria-label="attach files" title="attach files" onClick={() => fileRef.current?.click()}>
            +
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={(e) => onPickFiles(e.target.files)} />
          <ModelPicker value={settings?.model || ""} options={models} onChange={(v) => saveSettings({ model: v })} onOpen={() => loadModels(1)} />
          <ReasoningPicker value={settings?.reasoning_level || "auto"} options={getReasoningOptions(settings?.model || "")} onChange={(v) => saveSettings({ reasoning_level: v })} />
        </div>
        <div className="actions">
          {goal.trim() && (
            <span className={`est mono ${goalHot ? "hot" : ""}`}>~{fmtTok(goalEst)}</span>
          )}
          {activeRun && (activeRun.status === "running" || activeRun.status === "needs_input") && (
            <button className="ghost danger" onClick={cancel}>
              stop
              <kbd>ctrl c</kbd>
            </button>
          )}
          <button className="solid" disabled={busy || runActive || !goal.trim()} onClick={() => launch()}>
            send
            <kbd>enter</kbd>
          </button>
        </div>
      </div>
    </div>
  );

  function renderMessage(m: Message) {
    if (m.role === "user") {
      if (editingMsg === m.id) {
        return (
          <div key={m.id} className="bubble me editing">
            <textarea value={editText} onChange={(e) => setEditText(e.target.value)} onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); resendEdited(m.id); }
              if (e.key === "Escape") setEditingMsg(null);
            }} autoFocus />
            <div className="edit-actions">
              <button type="button" className="ghost" onClick={() => setEditingMsg(null)}>cancel</button>
              <button type="button" className="ghost" onClick={() => saveEdit(m.id)}>save</button>
              <button type="button" className="solid" disabled={!editText.trim()} onClick={() => resendEdited(m.id)}>send & run</button>
            </div>
          </div>
        );
      }
      return (
        <div key={m.id} className="msg-row">
          <div className="bubble me">
            <div>{m.content}</div>
            {!!m.attachments?.length && (
              <div className="attach-list">
                {m.attachments.map((f) => (
                  <span key={f.path} className="attach">{f.name}</span>
                ))}
              </div>
            )}
          </div>
          <div className="msg-ops">
            <button type="button" aria-label="edit & resend" title="edit & resend" onClick={() => { setEditingMsg(m.id); setEditText(m.content); }}>✎</button>
            <button type="button" aria-label="copy" title="copy" onClick={() => copyText(m.content)}>⧉</button>
            <button type="button" className="danger" aria-label="delete message" title="delete" onClick={() => setConfirmDelete({ messageId: m.id })}>×</button>
          </div>
        </div>
      );
    }
    const rid = m.run_id || "";
    const run = rid ? runs[rid] : null;
    const runningMsg = !!rid && !m.content && run !== null && ["running", "needs_input", "queued"].includes(run.status);
    return (
      <div key={m.id} className="msg-row">
        <div className="turn">
          {orchThink[rid] && (
            <details className="msg think-msg" open>
              <summary>▹ reasoning ({settings?.reasoning_level || "auto"})</summary>
              <div className="think-body">{orchThink[rid]}</div>
            </details>
          )}
          {plans[rid]?.length ? (
            <div className="msg plan">
              <span className="label">plan</span>
              {plans[rid].map((t, i) => (
                <div key={i} className="mono step">
                  <em>{String(i + 1).padStart(2, "0")}</em>
                  <span>
                    <b>{t.title}</b>
                    {t.goal}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
          {orchText[rid] && !m.content && <div className="msg">{orchText[rid]}</div>}
          {asks[rid] && (
            <div className="ask">
              {asks[rid]}
              <div className="row" style={{ marginTop: 10 }}>
                <input className="reply" value={input} onChange={(e) => setInput(e.target.value)} placeholder="reply…" />
                <button className="solid" onClick={reply}>send</button>
              </div>
            </div>
          )}
          {runningMsg && !m.content && !orchText[rid] && (
            <div className="typing"><span className="dot-mini" /><span className="dot-mini" /><span className="dot-mini" /> working…</div>
          )}
          {(m.content || run?.result) && (
            <div className="bubble them"><Markdown text={m.content || run?.result || ""} /></div>
          )}
        </div>
        {!runningMsg && (
          <div className="msg-ops">
            <button type="button" aria-label="regenerate" title="regenerate" onClick={regenerate}>↻</button>
            <button type="button" aria-label="copy" title="copy" onClick={() => copyText(m.content || run?.result || "")}>⧉</button>
            <button type="button" className="danger" aria-label="delete message" title="delete" onClick={() => setConfirmDelete({ messageId: m.id })}>×</button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="shell">
      <div className="aura" aria-hidden="true">
        <Iridescence color={[0.55, 0.62, 0.82]} speed={1.05} amplitude={0.18} mouseReact />
        <span className="mesh" />
        <span className="vignette" />
      </div>
      <div className={`app ${activeAgents.length ? "swarm-on" : "swarm-off"}`}>
        <aside className="panel side">
          <div className="brand">
            <div className="mark" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
            <div>
              <h1>iron</h1>
              <span>local swarm</span>
            </div>
          </div>

          <div className="side-tools">
            <button className="solid wide" onClick={newChat} aria-label="start new chat in current project">
              <span>new chat</span>
              <kbd>↵</kbd>
            </button>
            <ProjectPicker projects={projects} value={projectId} onChange={switchProject} onDelete={deleteProject} onNew={() => setShowNewProject(true)} />
            {project && (
              <div className="project-folder" title={project.workspace || "no folder assigned"}>
                <span className="folder-icon" aria-hidden="true">▦</span>
                <span className="folder-path mono">{project.workspace ? shortPath(project.workspace) : "no folder"}</span>
                <button className="icon-mini" aria-label="open folder in explorer" title="open in explorer" onClick={() => revealProject(projectId)}>
                  ⧉
                </button>
              </div>
            )}
            <div className="search-wrap">
              <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="search chats" aria-label="search chats" type="search" />
              {query && (
                <button className="search-clear" aria-label="clear search" onClick={() => setQuery("")}>
                  ×
                </button>
              )}
            </div>
          </div>

          <div className="side-divider" aria-hidden="true" />

          {projectFiles.length > 0 && (
            <div className="files-preview">
              <div className="section-head tight">
                <h3>files</h3>
                <span className="count">{projectFiles.length}</span>
              </div>
              <div className="file-list">
                {projectFiles.slice(0, 8).map((f) => (
                  <div key={f.name} className={`file-item ${f.is_dir ? "dir" : ""}`} title={f.name}>
                    <span className="file-icon" aria-hidden="true">{f.is_dir ? "▸" : "·"}</span>
                    <span className="file-name">{f.name}</span>
                    {!f.is_dir && <span className="file-size mono">{prettySize(f.size)}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="section-head">
            <h3>history</h3>
            <span className="count" aria-live="polite">
              {query.trim() ? `${visibleChats.length} / ${chats.filter((c) => c.project_id === projectId).length}` : `${visibleChats.length}`}
            </span>
          </div>
          <div className="side-scroll" role="list">
            {visibleChats.length === 0 ? (
              <div className="quiet">{query.trim() ? `no results for “${query.trim()}”` : "no chats yet — start one above"}</div>
            ) : (
              <>
                {visibleChats.filter((c) => c.pinned).length > 0 && (
                  <div className="history-group" role="group" aria-label="pinned chats">
                    <div className="history-label">pinned</div>
                    {visibleChats
                      .filter((c) => c.pinned)
                      .map((c) => (
                        <div key={c.id} role="listitem" className={`run-item ${c.id === chatId ? "active" : ""} pinned`}>
                          <button className="run-main" onClick={() => { setChatId(c.id); setPage("chat"); setFiles([]); }} title={c.title || "New chat"}>
                            <div className="g">{c.title || "New chat"}</div>
                            <div className="m">
                              <span>{c.messages.length} msgs</span>
                              <span className="mono">{fmtDay(c.updated_at)}</span>
                            </div>
                          </button>
                          <div className="run-ops">
                            <button type="button" className="active" aria-label="unpin" title="unpin" onClick={() => pinChat(c)}>
                              ★
                            </button>
                            <button type="button" aria-label="delete chat" title="delete" onClick={() => setConfirmDelete({ chatId: c.id })}>
                              ×
                            </button>
                          </div>
                        </div>
                      ))}
                  </div>
                )}
                <div className="history-group" role="group" aria-label="recent chats">
                  {visibleChats.filter((c) => c.pinned).length > 0 && <div className="history-label">recent</div>}
                  {visibleChats
                    .filter((c) => !c.pinned)
                    .map((c) => (
                      <div key={c.id} role="listitem" className={`run-item ${c.id === chatId ? "active" : ""}`}>
                        <button className="run-main" onClick={() => { setChatId(c.id); setPage("chat"); setFiles([]); }} title={c.title || "New chat"}>
                          <div className="g">{c.title || "New chat"}</div>
                          <div className="m">
                            <span>{c.messages.length} msgs</span>
                            <span className="mono">{fmtDay(c.updated_at)}</span>
                          </div>
                        </button>
                        <div className="run-ops">
                          <button type="button" aria-label="pin" title="pin" onClick={() => pinChat(c)}>
                            ☆
                          </button>
                          <button type="button" aria-label="delete chat" title="delete" onClick={() => setConfirmDelete({ chatId: c.id })}>
                            ×
                          </button>
                        </div>
                      </div>
                    ))}
                </div>
              </>
            )}
          </div>
          <button className={`nav-settings ${page === "settings" ? "on" : ""}`} onClick={() => setPage("settings")}>
            settings
          </button>
        </aside>

        {page === "settings" ? (
          <main className="panel center settings-page">
            <header className="runbar">
              <div>
                <div className="kicker">preferences</div>
                <h2>settings</h2>
              </div>
              <button className="ghost" onClick={() => setPage("chat")}>
                back
              </button>
            </header>
            {settings && (
              <div className="settings-grid">
                <section>
                  <h3>models</h3>
                  <div className="setting-field">
                    <span>worker</span>
                    <ModelPicker value={settings.model} options={models} onChange={(v) => saveSettings({ model: v })} placeholder="auto" onOpen={() => loadModels(1)} />
                  </div>
                  <div className="setting-field">
                    <span>orchestrator</span>
                    <ModelPicker value={settings.orchestrator_model} options={models} onChange={(v) => saveSettings({ orchestrator_model: v })} placeholder="same as worker" onOpen={() => loadModels(1)} />
                  </div>
                  <div className="setting-field">
                    <span>reasoning</span>
                    <ReasoningPicker value={settings.reasoning_level || "auto"} options={getReasoningOptions(settings.model || settings.orchestrator_model || "")} onChange={(v) => saveSettings({ reasoning_level: v })} />
                  </div>
                  <label>
                    ollama host
                    <input value={settings.ollama_host} onChange={(e) => saveSettings({ ollama_host: e.target.value })} />
                  </label>
                  {modelError && <div className="msg">{modelError}</div>}
                </section>
                <section>
                  <h3>workspace</h3>
                  <label>
                    default workspace
                    <input value={settings.workspace} onChange={(e) => saveSettings({ workspace: e.target.value })} />
                  </label>
                  {project && (
                    <label>
                      this project
                      <input value={project.workspace} onChange={(e) => saveProjectWorkspace(e.target.value)} />
                    </label>
                  )}
                  <label>
                    context window
                    <input type="number" value={settings.num_ctx} onChange={(e) => saveSettings({ num_ctx: Number(e.target.value) })} />
                  </label>
                  <label>
                    max concurrent agents
                    <input type="number" value={settings.max_concurrent} onChange={(e) => saveSettings({ max_concurrent: Number(e.target.value) })} />
                  </label>
                </section>
                <section>
                  <h3>context & memory</h3>
                  <label>
                    context target %
                    <input type="number" min={10} max={95} value={Math.round(settings.ctx_target * 100)} onChange={(e) => saveSettings({ ctx_target: Math.max(0.1, Math.min(0.95, (Number(e.target.value) || 60) / 100)) })} />
                  </label>
                  <label>
                    summary model
                    <input value={settings.summary_model} placeholder="auto (gemma4:e2b)" onChange={(e) => saveSettings({ summary_model: e.target.value })} />
                  </label>
                  <div className="quiet">
                    runs remember what their agents write to shared memory, per project — and chat history is compacted into rolling summaries to keep the context window small.
                  </div>
                </section>
                <section>
                  <h3>cloud orchestrator</h3>
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={settings.use_cloud_orchestrator}
                      onChange={(e) => saveSettings({ use_cloud_orchestrator: e.target.checked })}
                    />
                    use a remote model for planning
                  </label>
                  {settings.use_cloud_orchestrator && (
                    <div className="cloud-fields">
                      <label>
                        base url
                        <input value={settings.cloud_base_url} placeholder="https://api.openai.com/v1" onChange={(e) => saveSettings({ cloud_base_url: e.target.value })} />
                      </label>
                      <label>
                        model
                        <input value={settings.cloud_model} placeholder="gpt-4o, claude-3.5-sonnet, …" onChange={(e) => saveSettings({ cloud_model: e.target.value })} />
                      </label>
                      <label>
                        api key
                        <input type="password" value={settings.cloud_api_key} placeholder="sk-…" onChange={(e) => saveSettings({ cloud_api_key: e.target.value })} />
                      </label>
                    </div>
                  )}
                </section>
                <section>
                  <h3>mcp servers</h3>
                  <div className="quiet">
                    external MCP servers — their tools appear to worker agents as <span className="mono">mcp__server__tool</span>.
                  </div>
                  {mcpServers.length > 0 && (
                    <div className="mcp-list">
                      {mcpServers.map((s) => (
                        <div key={s.name} className={`mcp-item ${s.status === "ok" ? "ok" : ""}`}>
                          <div className="mcp-head">
                            <span className={`dot ${s.status === "ok" ? "on" : ""}`} />
                            <span className="mono mcp-name">{s.name}</span>
                            <span className="pill">{s.type}</span>
                            <span className="count">{s.tools} tools</span>
                          </div>
                          <div className="mcp-target mono">{s.command || s.url}</div>
                          {s.status !== "ok" && <div className="mcp-status err">{s.status}</div>}
                          <div className="mcp-actions">
                            <button type="button" className="ghost" disabled={!!mcpTesting} onClick={() => testMcpServer(s.name)}>
                              {mcpTesting === s.name ? "testing…" : "test"}
                            </button>
                            <button type="button" className="ghost danger" onClick={() => removeMcpServer(s.name)}>
                              remove
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mcp-form">
                    <input placeholder="name (filesystem, brave, …)" value={mcpForm.name} onChange={(e) => setMcpForm({ ...mcpForm, name: e.target.value })} />
                    <ModelPicker value={mcpForm.type} options={["stdio", "http"]} withPlaceholder={false} onChange={(v) => setMcpForm({ ...mcpForm, type: v })} />
                    {mcpForm.type === "stdio" ? (
                      <>
                        <input placeholder="command (npx, python, …)" value={mcpForm.command} onChange={(e) => setMcpForm({ ...mcpForm, command: e.target.value })} />
                        <input placeholder="args, space separated (-y @modelcontextprotocol/server-filesystem)" value={mcpForm.args} onChange={(e) => setMcpForm({ ...mcpForm, args: e.target.value })} />
                      </>
                    ) : (
                      <input placeholder="url (http://localhost:3001/mcp)" value={mcpForm.url} onChange={(e) => setMcpForm({ ...mcpForm, url: e.target.value })} />
                    )}
                    <button type="button" className="solid" onClick={addMcpServer}>
                      add
                    </button>
                  </div>
                </section>
              </div>
            )}
          </main>
        ) : (
          <main className={`panel center ${chat ? "has-run" : "idle"}`}>
            {!chat && (
              <div className="landing">
                <h2>give iron a goal</h2>
                <p>projects, history, uploads — then the swarm takes it</p>
                {composer}
                <div className="chips">
                  {SUGGESTIONS.map((s) => (
                    <button key={s.label} className="chip" onClick={() => { setGoal(s.goal); boxRef.current?.focus(); }}>
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {chat && (
              <>
                <header className="runbar">
                  <div className="runbar-head">
                    <div>
                      <div className="kicker">
                        <span>{project?.name || "home"}</span>
                        <span className="mono">{fmtDay(chat.updated_at)}</span>
                      </div>
                      {renaming ? (
                        <div className="rename-row">
                          <input
                            value={renameText}
                            onChange={(e) => setRenameText(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") renameChat(renameText.trim());
                              if (e.key === "Escape") setRenaming(false);
                            }}
                            autoFocus
                          />
                          <button type="button" className="ghost" onClick={() => renameChat(renameText.trim())}>save</button>
                        </div>
                      ) : (
                        <div className="title-row">
                          <h2>{chat.title || "New chat"}</h2>
                          <button type="button" className="icon-mini" aria-label="rename chat" title="rename" onClick={() => { setRenaming(true); setRenameText(chat.title || ""); }}>✎</button>
                        </div>
                      )}
                    </div>
                    {gaugeUsage && (
                      <div className={`ctx-meter ${gaugePct >= 85 ? "hot" : gaugePct >= 60 ? "warn" : "ok"}`} title={`${gaugeUsage.prompt} of ${gaugeUsage.ctx} tokens`}>
                        <span className="ctx-label mono">ctx {gaugePct}%</span>
                        <span className="ctx-bar"><i style={{ width: `${Math.max(2, gaugePct)}%` }} /></span>
                        <span className="ctx-num mono">{fmtTok(gaugeUsage.prompt)}/{fmtTok(gaugeUsage.ctx)}</span>
                      </div>
                    )}
                  </div>
                </header>
                <div className="stream" ref={streamRef}>
                  {chat.messages.filter((m) => m.role === "user" || m.content || m.run_id).map(renderMessage)}
                </div>
                {composer}
              </>
            )}

            <footer className="live">
              <div className={`dot ${live ? "on" : ""}`} />
              <span>{live ? "live" : "offline"}</span>
              <span className="sep" />
              <span>{activeAgents.length} agents</span>
              {running > 0 && <span className="hot">{running} running</span>}
            </footer>
          </main>
        )}

        <aside className="panel right">
          <div className="section-head">
            <h3>swarm</h3>
            <span className="count">{activeAgents.length}</span>
          </div>
          <div className="agents">
            {activeAgents.length === 0 && (
              <div className="quiet tall">
                workers appear here
                <small>one agent per discrete task</small>
              </div>
            )}
            {activeAgents.map((a) => (
              <div key={a.id} className={`agent ${a.depth > 1 ? "d2" : ""}`}>
                <div className="t">
                  <div className="name">{a.title}</div>
                  <span className={`pill ${a.status}`}>{a.status}</span>
                </div>
                <div className="goal">{a.goal}</div>
                <div className="stat">
                  d{a.depth} · step {a.steps}
                  {(a.prompt_tokens > 0 && a.ctx_window > 0) && (
                    <> · ctx {Math.min(100, Math.round((a.prompt_tokens / a.ctx_window) * 100))}%</>
                  )}
                </div>
                <div className="trace">
                  {(traces[a.id] || []).map((t) => (
                    <div
                      key={t.id}
                      className={t.kind === "think" ? "think" : t.kind === "tool" ? "tool" : t.kind === "error" ? "err" : t.kind === "result" ? "ok" : ""}
                    >
                      {t.kind === "think" ? "▹ " : t.kind === "tool" ? "⚙ " : t.kind === "result" ? "✓ " : ""}
                      {t.text}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </aside>
      </div>
      <Modal open={showNewProject} title="new project" placeholder="project name" initial="" onClose={() => setShowNewProject(false)} onConfirm={(name) => { setShowNewProject(false); newProject(name); }} />
      <Confirm
        open={!!confirmDelete?.chatId}
        title="delete chat?"
        body="This permanently removes the chat and its messages. You can't undo this."
        confirmLabel="delete"
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => { const id = confirmDelete?.chatId; if (id) removeChat(id); setConfirmDelete(null); }}
      />
      <Confirm
        open={!!confirmDelete?.projectId}
        title="delete project?"
        body="This permanently removes the project and all its chats. You can't undo this."
        confirmLabel="delete"
        onClose={() => setConfirmDelete(null)}
        onConfirm={confirmDeleteProject}
      />
      <Confirm
        open={!!confirmDelete?.messageId}
        title="delete message?"
        body="This message will be removed from the chat."
        confirmLabel="delete"
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => { const id = confirmDelete?.messageId; if (id) deleteMessage(id); }}
      />
      <Confirm
        open={confirmClear}
        title="clear chat?"
        body="This removes all messages from this chat. The thread history stays."
        confirmLabel="clear"
        onClose={() => setConfirmClear(false)}
        onConfirm={clearChat}
      />
      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import Iridescence from "./components/Iridescence";
import Confirm from "./components/Confirm";
import Markdown from "./components/Markdown";
import Modal from "./components/Modal";
import ModelPicker from "./components/ModelPicker";
import ProjectPicker from "./components/ProjectPicker";
import type {
  AgentSnapshot,
  Attachment,
  Chat,
  IronEvent,
  Message,
  Project,
  RunSnapshot,
  Settings,
  Trace,
} from "./types";

const SUGGESTIONS = [
  { label: "hello world", goal: "Create a tiny hello_world.py that prints iron, then run it." },
  { label: "map this workspace", goal: "Inspect the workspace, list the important files, and write a short architecture note." },
  { label: "split a real task", goal: "Create two small Python modules (math_utils.py and string_utils.py) with one function each, plus a README explaining them." },
];

const api = {
  async json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
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
  const streamRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => {
        setLive(true);
        loadModels(1);
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

  async function refreshChats(pid = projectId) {
    if (!pid) return;
    const c = await api.json<{ chats: Chat[] }>(`/api/chats?project_id=${pid}`);
    setChats(c.chats || []);
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
    await refreshChats(id);
  }

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
        last.text += text;
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
    const item = await api.json<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, workspace: settings?.workspace || "" }),
    });
    if ((item as unknown as { error?: string }).error) return;
    setProjects((prev) => [...prev, item]);
    await switchProject(item.id);
  }

  async function deleteProject(id: string) {
    if (projects.length <= 1) return;
    setConfirmDelete({ projectId: id });
  }

  async function confirmDeleteProject() {
    const id = confirmDelete?.projectId;
    if (!id) return;
    const res = await api.json<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" });
    if (!res.ok) return;
    const remaining = projects.filter((p) => p.id !== id);
    setProjects(remaining);
    if (projectId === id) await switchProject(remaining[0].id);
    else await refreshChats(projectId);
    setConfirmDelete(null);
    flash("project deleted");
  }

  async function launch(text = goal) {
    const next = text.trim();
    if (!next || busy || !projectId) return;
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
          attachments: files,
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
    await api.json(`/api/runs/${activeRun.id}/cancel`, { method: "POST" });
    setBusy(false);
  }

  async function reply() {
    if (!activeRun || !input.trim()) return;
    const text = input.trim();
    try {
      await api.json(`/api/runs/${activeRun.id}/input`, { method: "POST", body: JSON.stringify({ text }) });
    } catch {
      flash("backend unreachable");
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

  async function saveProjectWorkspace(workspace: string) {
    if (!project) return;
    const next = await api.json<Project>(`/api/projects/${project.id}`, {
      method: "PUT",
      body: JSON.stringify({ name: project.name, workspace }),
    });
    setProjects((prev) => prev.map((p) => (p.id === next.id ? next : p)));
  }

  async function removeChat(id: string) {
    await api.json(`/api/chats/${id}`, { method: "DELETE" });
    setChats((prev) => prev.filter((c) => c.id !== id));
    if (chatId === id) setChatId(null);
  }

  async function deleteMessage(id: string) {
    if (!chatId) return;
    const res = await api.json<{ ok: boolean; chat?: Chat }>(`/api/chats/${chatId}/messages/${id}`, { method: "DELETE" });
    if (res.ok) {
      setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, messages: c.messages.filter((m) => m.id !== id) } : c)));
      flash("message deleted");
    }
    setConfirmDelete(null);
  }

  async function saveEdit(id: string) {
    if (!chatId) return;
    const content = editText.trim();
    if (!content) return;
    const res = await api.json<{ ok: boolean; chat?: Chat }>(`/api/chats/${chatId}/messages/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    });
    if (res.ok && res.chat) {
      setChats((prev) => prev.map((c) => (c.id === chatId ? res.chat! : c)));
      setEditingMsg(null);
      flash("message updated");
    }
  }

  function flash(text: string) {
    setToast(text);
    window.setTimeout(() => setToast(""), 1800);
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
    await launch(lastUser.content);
  }

  async function resendEdited(id: string) {
    const content = editText.trim();
    if (!content) return;
    await saveEdit(id);
    await launch(content);
  }

  async function renameChat(title: string) {
    if (!chatId) return;
    const next = await api.json<Chat>(`/api/chats/${chatId}`, { method: "PATCH", body: JSON.stringify({ title }) });
    setChats((prev) => prev.map((c) => (c.id === next.id ? { ...c, ...next } : c)));
    setRenaming(false);
  }

  async function pinChat(c: Chat) {
    const next = await api.json<Chat>(`/api/chats/${c.id}`, {
      method: "PATCH",
      body: JSON.stringify({ pinned: !c.pinned }),
    });
    setChats((prev) => prev.map((x) => (x.id === next.id ? { ...x, ...next } : x)));
  }

  async function onPickFiles(list: FileList | null) {
    if (!list || !list.length) return;
    let id = chatId;
    if (!id) {
      if (!projectId) return;
      const created = await api.json<Chat>("/api/chats", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, title: "New chat" }),
      });
      id = created.id;
      setChats((prev) => [created, ...prev]);
      setChatId(id);
    }
    const uploaded: Attachment[] = [];
    for (const file of Array.from(list)) {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`/api/chats/${id}/upload`, { method: "POST", body });
      const data = (await res.json()) as Attachment & { error?: string };
      if (!data.error) uploaded.push({ name: data.name, path: data.path, size: data.size });
    }
    setFiles((prev) => [...prev, ...uploaded]);
    if (fileRef.current) fileRef.current.value = "";
  }

  const composer = (
    <div className="composer">
      {files.length > 0 && (
        <div className="attach-list">
          {files.map((f) => (
            <span key={f.path} className="attach">
              {f.name}
              <em>{prettySize(f.size)}</em>
              <button type="button" onClick={() => setFiles((prev) => prev.filter((x) => x.path !== f.path))}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        ref={boxRef}
        value={goal}
        placeholder={chat ? "message iron…" : "what should iron do?"}
        onChange={(e) => setGoal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            launch();
          }
        }}
      />
      <div className="row">
        <div className="meta">
          <button className="icon-btn" type="button" onClick={() => fileRef.current?.click()} title="attach files">
            +
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={(e) => onPickFiles(e.target.files)} />
          <ModelPicker value={settings?.model || ""} options={models} onChange={(v) => saveSettings({ model: v })} onOpen={() => loadModels(1)} />
        </div>
        <div className="actions">
          {activeRun && (activeRun.status === "running" || activeRun.status === "needs_input") && (
            <button className="ghost danger" onClick={cancel}>
              stop
            </button>
          )}
          <button className="solid" disabled={busy || !goal.trim()} onClick={() => launch()}>
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
            <button type="button" title="edit & resend" onClick={() => { setEditingMsg(m.id); setEditText(m.content); }}>✎</button>
            <button type="button" title="copy" onClick={() => copyText(m.content)}>⧉</button>
            <button type="button" className="danger" title="delete" onClick={() => setConfirmDelete({ messageId: m.id })}>×</button>
          </div>
        </div>
      );
    }
    const rid = m.run_id || "";
    const run = rid ? runs[rid] : null;
    const runningMsg = !!rid && !m.content && (!run || ["running", "needs_input", "queued"].includes(run.status));
    return (
      <div key={m.id} className="msg-row">
        <div className="turn">
          {orchThink[rid] && <div className="msg think-msg">▹ {orchThink[rid]}</div>}
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
          {runningMsg && !m.content && (
            <div className="typing"><span className="dot-mini" /><span className="dot-mini" /><span className="dot-mini" /> working…</div>
          )}
          {(m.content || run?.result) && (
            <div className="bubble them"><Markdown text={m.content || run?.result || ""} /></div>
          )}
          {run?.error && <div className="msg">{run.error}</div>}
        </div>
        {!runningMsg && (
          <div className="msg-ops">
            <button type="button" title="regenerate" onClick={regenerate}>↻</button>
            <button type="button" title="copy" onClick={() => copyText(m.content || run?.result || "")}>⧉</button>
            <button type="button" className="danger" title="delete" onClick={() => setConfirmDelete({ messageId: m.id })}>×</button>
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
            <button className="solid wide" onClick={newChat}>
              new chat
            </button>
            <ProjectPicker projects={projects} value={projectId} onChange={switchProject} onDelete={deleteProject} onNew={() => setShowNewProject(true)} />
            <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="search chats" />
          </div>

          <div className="section-head">
            <h3>history</h3>
            <span className="count">{visibleChats.length}</span>
          </div>
          <div className="side-scroll">
            {visibleChats.length === 0 && <div className="quiet">no chats yet</div>}
            {visibleChats.map((c) => (
              <div key={c.id} className={`run-item ${c.id === chatId ? "active" : ""}`}>
                <button className="run-main" onClick={() => { setChatId(c.id); setPage("chat"); }}>
                  <div className="g">{c.pinned ? "★ " : ""}{c.title || "New chat"}</div>
                  <div className="m">
                    <span>{c.messages.length} msgs</span>
                    <span className="mono">{fmtDay(c.updated_at)}</span>
                  </div>
                </button>
                <div className="run-ops">
                  <button type="button" onClick={() => pinChat(c)} title="pin">
                    ★
                  </button>
                  <button type="button" onClick={() => setConfirmDelete({ chatId: c.id })} title="delete">
                    ×
                  </button>
                </div>
              </div>
            ))}
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
                    <>
                      <label>
                        base url
                        <input value={settings.cloud_base_url} onChange={(e) => saveSettings({ cloud_base_url: e.target.value })} />
                      </label>
                      <label>
                        model
                        <input value={settings.cloud_model} onChange={(e) => saveSettings({ cloud_model: e.target.value })} />
                      </label>
                      <label>
                        api key
                        <input type="password" value={settings.cloud_api_key} onChange={(e) => saveSettings({ cloud_api_key: e.target.value })} />
                      </label>
                    </>
                  )}
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
                        <button type="button" className="icon-mini" title="rename" onClick={() => { setRenaming(true); setRenameText(chat.title || ""); }}>✎</button>
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

        <aside className="panel right" hidden={activeAgents.length === 0 && page === "chat"}>
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
                <div className="stat">d{a.depth} · step {a.steps}</div>
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
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

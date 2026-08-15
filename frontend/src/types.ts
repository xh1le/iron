export type AgentStatus =
  | "queued"
  | "running"
  | "thinking"
  | "tool"
  | "waiting"
  | "done"
  | "failed"
  | "cancelled";

export type RunStatus = "queued" | "running" | "needs_input" | "done" | "failed" | "cancelled";

export type AgentSnapshot = {
  id: string;
  run_id: string;
  parent_id: string | null;
  depth: number;
  title: string;
  goal: string;
  status: AgentStatus;
  model: string;
  steps: number;
  tokens: number;
  prompt_tokens: number;
  ctx_window: number;
  result: string;
  error: string;
  created_at: number;
  updated_at: number;
};

export type RunSnapshot = {
  id: string;
  goal: string;
  status: RunStatus;
  model: string;
  created_at: number;
  updated_at: number;
  result: string;
  error: string;
  chat_id?: string;
  project_id?: string;
  usage?: { prompt: number; ctx: number };
  agents: AgentSnapshot[];
  chat?: Chat;
};

export type Usage = { prompt: number; ctx: number };

export type Attachment = { name: string; path: string; size: number };

export type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  attachments?: Attachment[];
  run_id?: string | null;
  status?: string;
  usage?: Usage;
  ts: number;
};

export type Chat = {
  id: string;
  project_id: string;
  title: string;
  pinned?: boolean;
  created_at: number;
  updated_at: number;
  messages: Message[];
};

export type Project = {
  id: string;
  name: string;
  workspace: string;
  created_at: number;
  updated_at: number;
};

export type TraceKind = "think" | "token" | "tool" | "status" | "result" | "error" | "ask";

export type Trace = {
  id: string;
  ts: number;
  agentId: string;
  kind: TraceKind;
  text: string;
  tool?: string;
  phase?: string;
};

export type Settings = {
  ollama_host: string;
  model: string;
  orchestrator_model: string;
  cloud_base_url: string;
  cloud_api_key: string;
  cloud_model: string;
  use_cloud_orchestrator: boolean;
  num_ctx: number;
  max_ctx: number;
  temperature: number;
  max_concurrent: number;
  max_depth: number;
  max_agent_steps: number;
  max_orchestrator_rounds: number;
  ctx_target: number;
  summary_model: string;
  workspace: string;
  theme: string;
};

export type IronEvent = {
  type: string;
  ts?: number;
  run_id?: string;
  agent_id?: string;
  parent_id?: string;
  depth?: number;
  title?: string;
  status?: string;
  text?: string;
  tool?: string;
  args?: Record<string, unknown>;
  phase?: string;
  result?: string;
  error?: string;
  question?: string;
  agent?: AgentSnapshot;
  run?: RunSnapshot;
  tasks?: { title: string; goal: string }[];
  prompt_tokens?: number;
  num_ctx?: number;
  estimated?: boolean;
};

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentStatus = Literal[
    "queued",
    "running",
    "thinking",
    "tool",
    "waiting",
    "done",
    "failed",
    "cancelled",
]

RunStatus = Literal["queued", "running", "needs_input", "done", "failed", "cancelled"]


class ChatMessage(BaseModel):
    role: str
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class AgentSnapshot(BaseModel):
    id: str
    run_id: str
    parent_id: str | None = None
    depth: int = 0
    title: str
    goal: str
    status: AgentStatus = "queued"
    model: str = ""
    steps: int = 0
    tokens: int = 0
    prompt_tokens: int = 0
    ctx_window: int = 0
    result: str = ""
    error: str = ""
    created_at: int = 0
    updated_at: int = 0


class RunSnapshot(BaseModel):
    id: str
    goal: str
    status: RunStatus = "queued"
    model: str = ""
    created_at: int = 0
    updated_at: int = 0
    result: str = ""
    error: str = ""
    chat_id: str = ""
    project_id: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    agents: list[AgentSnapshot] = Field(default_factory=list)


class SettingsIn(BaseModel):
    ollama_host: str | None = None
    model: str | None = None
    orchestrator_model: str | None = None
    cloud_base_url: str | None = None
    cloud_api_key: str | None = None
    cloud_model: str | None = None
    use_cloud_orchestrator: bool | None = None
    num_ctx: int | None = None
    max_ctx: int | None = None
    temperature: float | None = None
    max_concurrent: int | None = None
    max_depth: int | None = None
    max_agent_steps: int | None = None
    max_orchestrator_rounds: int | None = None
    ctx_target: float | None = None
    summary_model: str | None = None
    workspace: str | None = None
    theme: str | None = None


class RunIn(BaseModel):
    goal: str
    workspace: str | None = None
    model: str | None = None
    chat_id: str | None = None
    project_id: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ProjectIn(BaseModel):
    name: str = "untitled"
    workspace: str = ""


class ChatIn(BaseModel):
    project_id: str
    title: str = "New chat"


class ChatPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    project_id: str | None = None

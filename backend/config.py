from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def iron_home() -> Path:
    return Path.home() / ".iron"


def default_workspace() -> Path:
    ws = Path(__file__).resolve().parent.parent / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


class Settings(BaseModel):
    ollama_host: str = "http://127.0.0.1:11434"
    model: str = ""
    orchestrator_model: str = ""
    cloud_base_url: str = ""
    cloud_api_key: str = ""
    cloud_model: str = ""
    use_cloud_orchestrator: bool = False
    num_ctx: int = 65536
    max_ctx: int = 131072
    temperature: float = 0.25
    max_concurrent: int = 12
    max_depth: int = 2
    max_agent_steps: int = 24
    max_orchestrator_rounds: int = 6
    workspace: str = str(default_workspace())
    theme: str = "iron"

    def resolved_model(self) -> str:
        return self.model or "gemma4:e4b"

    def resolved_orchestrator_model(self) -> str:
        return self.orchestrator_model or self.resolved_model()

    def ctx(self) -> int:
        return max(4096, min(int(self.num_ctx), int(self.max_ctx)))


def config_path() -> Path:
    iron_home().mkdir(parents=True, exist_ok=True)
    return iron_home() / "config.json"


def load_settings() -> Settings:
    path = config_path()
    if not path.exists():
        settings = Settings()
        save_settings(settings)
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Settings.model_validate(data)
    except Exception:
        try:
            backup = path.with_name(f"config.json.corrupt-{int(time.time())}")
            path.replace(backup)
        except OSError:
            pass
        return Settings()


def save_settings(settings: Settings) -> None:
    path = config_path()
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


def merge_settings(current: Settings, patch: dict[str, Any]) -> Settings:
    data = current.model_dump()
    for key, value in patch.items():
        if key in data and value is not None:
            data[key] = value
    updated = Settings.model_validate(data)
    save_settings(updated)
    return updated

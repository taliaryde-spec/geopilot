"""HTTP request and response contracts for the local GeoPilot API."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ApiSettings(BaseModel):
    """Resolved local paths and safety limits owned by the API process."""

    workspace_root: Path = Field(default_factory=Path.cwd)
    plans_directory: Path = Path("artifacts") / "plans"
    runs_directory: Path = Path("artifacts") / "runs"
    knowledge_index: Path = Path("artifacts") / "rag" / "index.json"
    model_cache: Path = Path("artifacts") / "models" / "fastembed"
    memory_path: Path = Path("artifacts") / "memory" / "profile.json"
    trace_path: Path = Path("artifacts") / "traces" / "agent_runs.jsonl"

    @model_validator(mode="after")
    def resolve_local_paths(self) -> "ApiSettings":
        root = self.workspace_root.resolve()

        def resolve_under_root(path: Path) -> Path:
            resolved = (path if path.is_absolute() else root / path).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"API storage path must remain in workspace: {path}")
            return resolved

        self.workspace_root = root
        self.plans_directory = resolve_under_root(self.plans_directory)
        self.runs_directory = resolve_under_root(self.runs_directory)
        self.knowledge_index = resolve_under_root(self.knowledge_index)
        self.model_cache = resolve_under_root(self.model_cache)
        self.memory_path = resolve_under_root(self.memory_path)
        self.trace_path = resolve_under_root(self.trace_path)
        return self


class HealthResponse(BaseModel):
    """Small readiness response that never requires model credentials."""

    status: Literal["ok"] = "ok"
    service: Literal["geopilot-api"] = "geopilot-api"
    version: str = "0.1.0"


class DatasetInspectRequest(BaseModel):
    """Path-based local dataset intake request."""

    source: str = Field(min_length=1, max_length=1024)
    longitude_column: str = Field(default="longitude", min_length=1, max_length=128)
    latitude_column: str = Field(default="latitude", min_length=1, max_length=128)


class AgentRunRequest(BaseModel):
    """Bounded Agent request; provider credentials remain server-side."""

    prompt: str = Field(min_length=1, max_length=20_000)
    max_turns: int = Field(default=6, ge=1, le=8)
    max_output_tokens: int | None = Field(default=None, ge=64, le=8192)
    memory_enabled: bool = True
    memory_namespace: str = Field(
        default="default",
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
    )


class AgentToolSummary(BaseModel):
    """Safe tool metadata returned to an API client."""

    name: str
    success: bool
    error_code: str | None = None


class AgentRunResponse(BaseModel):
    """Final Agent answer plus bounded operational metadata."""

    answer: str
    model_turns: int = Field(ge=1)
    tools: list[AgentToolSummary]
    plan_ids: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class RejectPlanRequest(BaseModel):
    """Explicit human rejection reason."""

    reason: str = Field(min_length=1, max_length=1000)


class ApiErrorDetail(BaseModel):
    """Stable machine-readable API error body."""

    code: str
    message: str
    context: dict[str, Any] | None = None


class ApiErrorResponse(BaseModel):
    """Top-level error envelope shared by application exceptions."""

    error: ApiErrorDetail

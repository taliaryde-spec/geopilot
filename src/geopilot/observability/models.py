"""Privacy-bounded contracts for local Agent execution traces."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AgentTraceStatus(StrEnum):
    """Terminal status recorded for one Agent invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolTraceEvent(BaseModel):
    """Tool metadata that deliberately excludes arguments and outputs."""

    sequence: int = Field(ge=1)
    name: str = Field(min_length=1)
    success: bool
    error_code: str | None = None


class AgentTrace(BaseModel):
    """One redacted, append-only Agent run record."""

    schema_version: Literal["1.0"] = "1.0"
    trace_id: str = Field(pattern=r"^trace_[a-f0-9]{32}$")
    started_at: datetime
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: AgentTraceStatus
    duration_ms: float = Field(ge=0)
    model_turns: int = Field(ge=0)
    tool_calls: list[ToolTraceEvent]
    final_answer_characters: int = Field(ge=0)
    error_code: str | None = None

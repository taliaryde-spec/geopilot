"""Append-only local JSONL persistence for redacted Agent traces."""

import json
import os
from enum import StrEnum
from pathlib import Path

from pydantic import ValidationError

from geopilot.observability.models import AgentTrace, AgentTraceStatus

DEFAULT_TRACE_PATH = Path("artifacts") / "traces" / "agent_runs.jsonl"


class TraceStoreErrorCode(StrEnum):
    """Stable error codes exposed by trace persistence."""

    INVALID_STORE = "invalid_trace_store"
    IO_ERROR = "trace_io_error"


class TraceStoreError(RuntimeError):
    """Trace persistence failure with a stable machine-readable code."""

    def __init__(self, code: TraceStoreErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class TraceStore:
    """Persist independent JSON records without rewriting trace history."""

    def __init__(self, path: str | Path = DEFAULT_TRACE_PATH) -> None:
        self.path = Path(path).resolve()

    def append(self, trace: AgentTrace) -> None:
        """Append and fsync one compact record; never store model payloads."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(trace.model_dump_json())
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise TraceStoreError(
                TraceStoreErrorCode.IO_ERROR,
                f"Could not append Agent trace: {self.path}",
            ) from error

    def list_traces(
        self,
        *,
        limit: int = 20,
        status: AgentTraceStatus | None = None,
    ) -> list[AgentTrace]:
        """Return newest matching traces from a bounded local history."""
        if not 1 <= limit <= 500:
            raise ValueError("Trace list limit must be between 1 and 500.")
        if not self.path.exists():
            return []
        try:
            records = [
                AgentTrace.model_validate_json(line)
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValidationError, json.JSONDecodeError) as error:
            raise TraceStoreError(
                TraceStoreErrorCode.INVALID_STORE,
                f"Agent trace store is invalid: {self.path}",
            ) from error
        selected = (
            records
            if status is None
            else [record for record in records if record.status is status]
        )
        return list(reversed(selected[-limit:]))

"""Create privacy-bounded traces without retaining model-visible content."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from geopilot.agent.models import ToolResult
from geopilot.observability.models import (
    AgentTrace,
    AgentTraceStatus,
    ToolTraceEvent,
)


def build_agent_trace(
    prompt: str,
    *,
    provider: str,
    model_name: str,
    status: AgentTraceStatus,
    duration_ms: float,
    model_turns: int,
    tool_results: Sequence[ToolResult] = (),
    final_answer: str | None = None,
    error_code: str | None = None,
    id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AgentTrace:
    """Convert one run into metadata that omits raw prompts and tool payloads."""
    selected_id_factory = id_factory or (lambda: uuid4().hex)
    selected_clock = clock or (lambda: datetime.now(UTC))
    bounded_duration_ms = max(0.0, duration_ms)
    finished_at = selected_clock()
    return AgentTrace(
        trace_id=f"trace_{selected_id_factory()}",
        started_at=finished_at - timedelta(milliseconds=bounded_duration_ms),
        provider=provider,
        model_name=model_name,
        prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
        status=status,
        duration_ms=bounded_duration_ms,
        model_turns=max(0, model_turns),
        tool_calls=[
            ToolTraceEvent(
                sequence=sequence,
                name=result.name,
                success=result.success,
                error_code=result.error_code,
            )
            for sequence, result in enumerate(tool_results, start=1)
        ],
        final_answer_characters=len(final_answer or ""),
        error_code=error_code,
    )

"""Tests for privacy-bounded Agent trace creation and persistence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from geopilot.agent.models import ToolResult
from geopilot.observability import (
    AgentTraceStatus,
    TraceStore,
    TraceStoreError,
    build_agent_trace,
)


def _trace(*, status: AgentTraceStatus = AgentTraceStatus.SUCCEEDED):
    return build_agent_trace(
        "请检查 secret-dataset.geojson",
        provider="test-provider",
        model_name="test-model",
        status=status,
        duration_ms=12.5,
        model_turns=2,
        tool_results=[
            ToolResult(
                tool_call_id="call-secret",
                name="inspect_dataset",
                success=True,
                output={"secret_column": "must-not-be-stored"},
            )
        ],
        final_answer="这里包含不应进入 Trace 的完整回答。",
        id_factory=lambda: "a" * 32,
        clock=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )


def test_build_agent_trace_redacts_prompt_arguments_outputs_and_answer() -> None:
    trace = _trace()
    serialized = trace.model_dump_json()

    assert trace.trace_id == f"trace_{'a' * 32}"
    assert len(trace.prompt_sha256) == 64
    assert trace.final_answer_characters == len("这里包含不应进入 Trace 的完整回答。")
    assert trace.tool_calls[0].name == "inspect_dataset"
    assert "secret-dataset" not in serialized
    assert "secret_column" not in serialized
    assert "must-not-be-stored" not in serialized
    assert "完整回答" not in serialized
    assert "call-secret" not in serialized


def test_trace_store_appends_and_filters_newest_first(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "agent-runs.jsonl")
    first = _trace()
    second = _trace(status=AgentTraceStatus.FAILED).model_copy(
        update={"trace_id": f"trace_{'b' * 32}", "error_code": "agent_max_turns"}
    )

    store.append(first)
    store.append(second)

    assert [trace.trace_id for trace in store.list_traces()] == [
        second.trace_id,
        first.trace_id,
    ]
    assert store.list_traces(status=AgentTraceStatus.FAILED) == [second]
    assert store.list_traces(status=AgentTraceStatus.SUCCEEDED) == [first]


def test_trace_store_returns_empty_when_file_is_missing(tmp_path: Path) -> None:
    assert TraceStore(tmp_path / "missing.jsonl").list_traces() == []


def test_trace_store_rejects_corrupt_history(tmp_path: Path) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(TraceStoreError, match="trace store is invalid"):
        TraceStore(path).list_traces()


def test_trace_store_enforces_bounded_query_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 500"):
        TraceStore(tmp_path / "trace.jsonl").list_traces(limit=0)

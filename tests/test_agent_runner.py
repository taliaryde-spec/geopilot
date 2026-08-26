"""Tests for the provider-neutral GeoPilot Agent loop."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from geopilot.agent.models import (
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
)
from geopilot.agent.runner import (
    AgentMaxTurnsError,
    AgentProtocolError,
    AgentRunner,
)
from geopilot.agent.tool_adapters import build_default_tool_registry

SAMPLE_DATASET = (
    Path(__file__).resolve().parents[1] / "examples" / "data" / "facilities.csv"
)


class ScriptedChatModel:
    """Deterministic model used to test Agent control flow without an API."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses.copy()
        self.requests: list[tuple[list[AgentMessage], list[ToolDefinition]]] = []

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        self.requests.append((list(messages), list(tools)))
        if not self._responses:
            raise AssertionError("Scripted model has no response left")
        return self._responses.pop(0)


def test_agent_calls_dataset_tool_and_returns_final_answer() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="inspect_dataset",
                        arguments={"source": str(SAMPLE_DATASET)},
                    )
                ]
            ),
            ModelResponse(
                content=(
                    "数据包含 5 个点要素，CRS 为 EPSG:4326，当前检查允许继续分析。"
                )
            ),
        ]
    )
    runner = AgentRunner(model, build_default_tool_registry())

    result = runner.run(f"请检查数据集 {SAMPLE_DATASET}")

    assert result.model_turns == 2
    assert result.final_answer.startswith("数据包含 5 个点要素")
    assert len(result.tool_results) == 1
    assert result.tool_results[0].success is True
    assert result.tool_results[0].output is not None
    assert result.tool_results[0].output["profile"]["feature_count"] == 5
    assert [message.role for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert "CRS" in (model.requests[0][0][0].content or "")
    assert "Never guess a target CRS" in (model.requests[0][0][0].content or "")
    assert model.requests[0][1][0].name == "inspect_dataset"
    assert "source" in model.requests[0][1][0].input_schema["properties"]


def test_agent_calls_metric_crs_tool_and_returns_computed_epsg() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-crs",
                        name="recommend_metric_crs",
                        arguments={"source": str(SAMPLE_DATASET)},
                    )
                ]
            ),
            ModelResponse(
                content="工具计算结果为 EPSG:32651，可用于后续米制距离分析。"
            ),
        ]
    )
    runner = AgentRunner(model, build_default_tool_registry())

    result = runner.run(f"为 {SAMPLE_DATASET} 推荐距离分析坐标系")

    assert result.tool_results[0].success is True
    assert result.tool_results[0].output is not None
    assert result.tool_results[0].output["recommended_epsg"] == 32651
    assert result.tool_results[0].output["requires_reprojection"] is True
    assert result.final_answer.startswith("工具计算结果为 EPSG:32651")
    assert [definition.name for definition in model.requests[0][1]] == [
        "inspect_dataset",
        "recommend_metric_crs",
    ]


def test_agent_returns_unknown_tool_error_to_model() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(id="call-unknown", name="missing_tool", arguments={})
                ]
            ),
            ModelResponse(content="请求的工具不存在，因此没有执行分析。"),
        ]
    )
    runner = AgentRunner(model, build_default_tool_registry())

    result = runner.run("调用一个不存在的工具")

    assert result.tool_results[0].success is False
    assert result.tool_results[0].error_code == "unknown_tool"
    assert result.messages[3].role == "tool"
    assert "unknown_tool" in (result.messages[3].content or "")


def test_agent_returns_invalid_arguments_error_to_model() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(id="call-invalid", name="inspect_dataset", arguments={})
                ]
            ),
            ModelResponse(content="缺少数据路径，因此没有执行检查。"),
        ]
    )
    runner = AgentRunner(model, build_default_tool_registry())

    result = runner.run("检查一个没有提供路径的数据集")

    assert result.tool_results[0].success is False
    assert result.tool_results[0].error_code == "invalid_tool_arguments"


def test_agent_rejects_empty_model_response() -> None:
    model = ScriptedChatModel([ModelResponse()])
    runner = AgentRunner(model, build_default_tool_registry())

    with pytest.raises(AgentProtocolError, match="neither a final answer"):
        runner.run("检查数据")


def test_agent_stops_after_maximum_model_turns() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(tool_calls=[ToolCall(id="call-1", name="missing_tool")]),
            ModelResponse(tool_calls=[ToolCall(id="call-2", name="missing_tool")]),
        ]
    )
    runner = AgentRunner(
        model,
        build_default_tool_registry(),
        max_model_turns=2,
    )

    with pytest.raises(AgentMaxTurnsError, match="limit of 2"):
        runner.run("持续调用工具")

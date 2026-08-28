"""Tests for end-to-end Agent result, process, and safety evaluation."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel

from geopilot.agent.models import AgentMessage, ModelResponse, ToolCall, ToolDefinition
from geopilot.agent.registry import AgentTool, ToolRegistry
from geopilot.agent.runner import AgentRunner
from geopilot.evaluation import (
    AgentEvaluationCase,
    ExpectedTaskOutcome,
    ObservedTaskOutcome,
    evaluate_agent,
    load_agent_evaluation_cases,
)


class ScriptedChatModel:
    """Return fixed responses so evaluation tests never call an external API."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses.copy()

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        del messages, tools
        if not self._responses:
            raise AssertionError("Scripted model has no response left")
        return self._responses.pop(0)


class LookupArguments(BaseModel):
    """Small validated tool input used only by evaluator tests."""

    query: str


class LookupResult(BaseModel):
    """Small structured tool result used only by evaluator tests."""

    answer: str


def _lookup(arguments: BaseModel) -> BaseModel:
    validated = LookupArguments.model_validate(arguments)
    return LookupResult(answer=f"found:{validated.query}")


def _failing_lookup(arguments: BaseModel) -> BaseModel:
    LookupArguments.model_validate(arguments)
    raise ValueError("The requested source is unavailable")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        AgentTool(
            name="lookup",
            description="Look up a test value.",
            input_model=LookupArguments,
            handler=_lookup,
        )
    )
    registry.register(
        AgentTool(
            name="failing_lookup",
            description="Return a recoverable test failure.",
            input_model=LookupArguments,
            handler=_failing_lookup,
            recoverable_errors=(ValueError,),
        )
    )
    return registry


def test_evaluator_scores_completed_and_correct_failure_cases() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-success",
                        name="lookup",
                        arguments={"query": "EPSG"},
                    )
                ]
            ),
            ModelResponse(content="检查完成，结果包含 EPSG:4326。"),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-failure",
                        name="failing_lookup",
                        arguments={"query": "missing"},
                    )
                ]
            ),
            ModelResponse(content="数据不可用，因此无法继续。"),
        ]
    )
    cases = [
        AgentEvaluationCase(
            case_id="completed_case",
            prompt="检查数据",
            required_tools=["lookup"],
            required_answer_contains=["EPSG:4326"],
            max_model_turns=2,
            max_tool_calls=1,
        ),
        AgentEvaluationCase(
            case_id="correct_failure_case",
            prompt="检查缺失数据",
            expected_outcome=ExpectedTaskOutcome.CORRECT_FAILURE,
            required_tools=["failing_lookup"],
            required_answer_contains=["无法继续"],
            expected_tool_error_codes=["tool_execution_error"],
            max_model_turns=2,
            max_tool_calls=1,
        ),
    ]

    result = evaluate_agent(
        AgentRunner(model, _registry()),
        cases,
        provider="test",
        model_name="scripted",
    )

    assert result.task_success_rate == 1.0
    assert result.completed_rate == 0.5
    assert result.correct_failure_rate == 0.5
    assert result.error_recovery_rate == 1.0
    assert result.mean_required_tool_recall == 1.0
    assert result.tool_call_success_rate == 0.5
    assert result.mean_step_efficiency == 1.0
    assert [case.observed_outcome for case in result.cases] == [
        ObservedTaskOutcome.COMPLETED,
        ObservedTaskOutcome.CORRECT_FAILURE,
    ]


def test_evaluator_rejects_duplicate_and_forbidden_tool_calls() -> None:
    duplicate_call = ToolCall(
        id="call-duplicate-1",
        name="lookup",
        arguments={"query": "same"},
    )
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    duplicate_call,
                    duplicate_call.model_copy(update={"id": "call-duplicate-2"}),
                ]
            ),
            ModelResponse(content="完成。"),
        ]
    )
    evaluation_case = AgentEvaluationCase(
        case_id="duplicate_forbidden_case",
        prompt="执行检查",
        required_tools=["lookup"],
        forbidden_tools=["lookup_extra"],
        required_answer_contains=["完成"],
        max_model_turns=2,
        max_tool_calls=2,
    )

    result = evaluate_agent(
        AgentRunner(model, _registry()),
        [evaluation_case],
        provider="test",
        model_name="scripted",
    )

    assert result.task_success_rate == 0.0
    assert result.duplicate_tool_call_rate == 0.5
    assert result.mean_step_efficiency == 0.5
    assert result.cases[0].duplicate_tool_call_count == 1


def test_evaluator_marks_forbidden_tool_use_as_failure() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-forbidden",
                        name="lookup",
                        arguments={"query": "unexpected"},
                    )
                ]
            ),
            ModelResponse(content="直接回答。"),
        ]
    )
    evaluation_case = AgentEvaluationCase(
        case_id="forbidden_case",
        prompt="不要调用工具",
        forbidden_tools=["lookup"],
        required_answer_contains=["回答"],
        max_model_turns=2,
        max_tool_calls=1,
    )

    result = evaluate_agent(
        AgentRunner(model, _registry()),
        [evaluation_case],
        provider="test",
        model_name="scripted",
    )

    assert result.forbidden_tool_violation_rate == 1.0
    assert result.cases[0].forbidden_tool_call_count == 1
    assert result.cases[0].passed is False


def test_evaluator_converts_max_turns_into_a_scored_failure() -> None:
    model = ScriptedChatModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-loop",
                        name="lookup",
                        arguments={"query": "loop"},
                    )
                ]
            )
        ]
    )
    evaluation_case = AgentEvaluationCase(
        case_id="loop_case",
        prompt="循环",
        required_tools=["lookup"],
        max_model_turns=1,
        max_tool_calls=1,
    )

    result = evaluate_agent(
        AgentRunner(model, _registry(), max_model_turns=1),
        [evaluation_case],
        provider="test",
        model_name="scripted",
    )

    assert result.task_success_rate == 0.0
    assert result.cases[0].runtime_error is not None
    assert "limit of 1" in result.cases[0].runtime_error
    assert result.cases[0].tool_names == ["lookup"]


def test_load_agent_evaluation_cases_validates_json(tmp_path: Path) -> None:
    source = tmp_path / "agent-cases.json"
    source.write_text(
        json.dumps(
            [
                {
                    "case_id": "inspect_valid",
                    "prompt": "检查示例数据",
                    "required_tools": ["lookup"],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = load_agent_evaluation_cases(source)

    assert cases[0].case_id == "inspect_valid"

    source.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="At least one"):
        load_agent_evaluation_cases(source)


def test_correct_failure_case_requires_expected_error_code() -> None:
    with pytest.raises(ValueError, match="require expected error codes"):
        AgentEvaluationCase(
            case_id="invalid_failure_case",
            prompt="检查失败",
            expected_outcome=ExpectedTaskOutcome.CORRECT_FAILURE,
        )

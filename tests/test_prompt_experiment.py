"""Tests for versioned prompts and controlled prompt comparisons."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from geopilot.agent.models import (
    AgentMessage,
    ModelResponse,
    ModelUsage,
    ToolDefinition,
)
from geopilot.agent.prompting import (
    DEFAULT_PROMPT_VARIANT,
    PromptSpec,
    PromptVariant,
    get_prompt_spec,
    list_prompt_specs,
)
from geopilot.agent.prompting.templates import GEOPILOT_SYSTEM_PROMPT
from geopilot.agent.registry import ToolRegistry
from geopilot.evaluation import AgentEvaluationCase, run_prompt_experiment


class PromptAwareModel:
    """Capture the selected system prompt and return deterministic usage."""

    def __init__(self, seen_prompts: list[str]) -> None:
        self._seen_prompts = seen_prompts

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        del tools
        system_prompt = messages[0].content or ""
        self._seen_prompts.append(system_prompt)
        return ModelResponse(
            content="done",
            usage=ModelUsage(input_tokens=20, output_tokens=2, total_tokens=22),
        )


def _spec(variant: PromptVariant, text: str) -> PromptSpec:
    return PromptSpec(
        variant=variant,
        version="test-1",
        description=f"Test prompt {variant.value}.",
        system_prompt=text,
        includes_few_shot=variant is PromptVariant.STRUCTURED_FEW_SHOT,
    )


def test_prompt_catalog_is_versioned_and_keeps_structured_default() -> None:
    specs = list_prompt_specs()

    assert [spec.variant for spec in specs] == list(PromptVariant)
    assert DEFAULT_PROMPT_VARIANT is PromptVariant.STRUCTURED
    assert get_prompt_spec(DEFAULT_PROMPT_VARIANT).system_prompt == (
        GEOPILOT_SYSTEM_PROMPT
    )
    assert get_prompt_spec(PromptVariant.STRUCTURED_FEW_SHOT).includes_few_shot


def test_prompt_experiment_holds_cases_and_model_settings_constant() -> None:
    seen_prompts: list[str] = []
    cases = [
        AgentEvaluationCase(
            case_id="answer_only",
            prompt="Return done.",
            required_answer_contains=["done"],
            max_model_turns=1,
            max_tool_calls=0,
        )
    ]
    specs = [
        _spec(PromptVariant.MINIMAL, "minimal prompt"),
        _spec(PromptVariant.STRUCTURED, "structured prompt"),
    ]
    created_at = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)

    result = run_prompt_experiment(
        cases,
        specs,
        model_factory=lambda spec: PromptAwareModel(seen_prompts),
        tool_registry_factory=lambda spec: ToolRegistry(),
        provider="test-provider",
        model_name="test-model",
        max_model_turns=1,
        now=lambda: created_at,
    )

    assert result.created_at == created_at
    assert result.case_count == 1
    assert [item.variant for item in result.variants] == [
        PromptVariant.MINIMAL,
        PromptVariant.STRUCTURED,
    ]
    assert seen_prompts == ["minimal prompt", "structured prompt"]
    assert all(item.evaluation.task_success_rate == 1.0 for item in result.variants)
    assert all(item.evaluation.total_tokens == 22 for item in result.variants)
    assert all(item.evaluation.usage_coverage_rate == 1.0 for item in result.variants)
    assert len(result.variants[0].system_prompt_sha256) == 64


def test_prompt_experiment_requires_two_unique_variants() -> None:
    case = AgentEvaluationCase(case_id="answer_only", prompt="Return done.")
    minimal = _spec(PromptVariant.MINIMAL, "minimal prompt")
    factory = lambda spec: PromptAwareModel([])
    registry_factory = lambda spec: ToolRegistry()

    with pytest.raises(ValueError, match="at least two"):
        run_prompt_experiment(
            [case],
            [minimal],
            model_factory=factory,
            tool_registry_factory=registry_factory,
            provider="test",
            model_name="test-model",
        )

    with pytest.raises(ValueError, match="unique"):
        run_prompt_experiment(
            [case],
            [minimal, minimal],
            model_factory=factory,
            tool_registry_factory=registry_factory,
            provider="test",
            model_name="test-model",
        )

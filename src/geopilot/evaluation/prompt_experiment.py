"""Controlled system-prompt comparison over the same Agent task set."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from geopilot.agent.client import ChatModel
from geopilot.agent.prompting import PromptSpec
from geopilot.agent.registry import ToolRegistry
from geopilot.agent.runner import AgentRunner
from geopilot.evaluation.agent_evaluator import evaluate_agent
from geopilot.evaluation.models import (
    AgentEvaluationCase,
    AgentEvaluationResult,
    PromptExperimentResult,
    PromptVariantEvaluation,
)

ModelFactory = Callable[[PromptSpec], ChatModel]
ToolRegistryFactory = Callable[[PromptSpec], ToolRegistry]


def run_prompt_experiment(
    cases: list[AgentEvaluationCase],
    prompt_specs: list[PromptSpec],
    *,
    model_factory: ModelFactory,
    tool_registry_factory: ToolRegistryFactory,
    provider: str,
    model_name: str,
    max_model_turns: int = 6,
    now: Callable[[], datetime] | None = None,
) -> PromptExperimentResult:
    """Compare prompts while holding model, tools, cases, and budgets fixed."""
    if not cases:
        raise ValueError("Prompt experiment requires at least one evaluation case.")
    if len(prompt_specs) < 2:
        raise ValueError("Prompt experiment requires at least two prompt variants.")
    variants = [spec.variant for spec in prompt_specs]
    if len(variants) != len(set(variants)):
        raise ValueError("Prompt experiment variants must be unique.")
    if max_model_turns < 1:
        raise ValueError("max_model_turns must be at least 1")

    evaluations: list[PromptVariantEvaluation] = []
    for spec in prompt_specs:
        runner = AgentRunner(
            model_factory(spec),
            tool_registry_factory(spec),
            system_prompt=spec.system_prompt,
            max_model_turns=max_model_turns,
        )
        evaluation = evaluate_agent(
            runner,
            cases,
            provider=provider,
            model_name=model_name,
        )
        evaluations.append(_variant_evaluation(spec, evaluation))

    clock = now or (lambda: datetime.now(UTC))
    return PromptExperimentResult(
        created_at=clock(),
        provider=provider,
        model_name=model_name,
        case_count=len(cases),
        controlled_variables=[
            "model",
            "tool definitions",
            "evaluation cases",
            "maximum model turns",
            "knowledge index",
        ],
        variants=evaluations,
    )


def _variant_evaluation(
    spec: PromptSpec,
    evaluation: AgentEvaluationResult,
) -> PromptVariantEvaluation:
    return PromptVariantEvaluation(
        variant=spec.variant,
        prompt_version=spec.version,
        description=spec.description,
        includes_few_shot=spec.includes_few_shot,
        system_prompt_characters=len(spec.system_prompt),
        system_prompt_sha256=sha256(spec.system_prompt.encode("utf-8")).hexdigest(),
        evaluation=evaluation,
    )

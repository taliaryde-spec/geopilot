"""Rule-based evaluation of complete Agent answers and execution traces."""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter, ValidationError

from geopilot.agent.runner import (
    AgentMaxTurnsError,
    AgentProtocolError,
    AgentRunner,
)
from geopilot.evaluation.models import (
    AgentCaseEvaluation,
    AgentEvaluationCase,
    AgentEvaluationResult,
    ExpectedTaskOutcome,
    ObservedTaskOutcome,
)


def load_agent_evaluation_cases(
    source: str | Path,
) -> list[AgentEvaluationCase]:
    """Load a version-controlled JSON array of Agent evaluation cases."""
    path = Path(source).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Agent evaluation file does not exist: {path}")
    try:
        cases = TypeAdapter(list[AgentEvaluationCase]).validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        raise ValueError(f"Agent evaluation file is invalid: {path}") from error
    if not cases:
        raise ValueError("At least one Agent evaluation case is required.")
    return cases


def evaluate_agent(
    runner: AgentRunner,
    cases: list[AgentEvaluationCase],
    *,
    provider: str,
    model_name: str,
    timer: Callable[[], float] = perf_counter,
) -> AgentEvaluationResult:
    """Run fixed tasks and score answer, tool, efficiency, and safety rules."""
    if not cases:
        raise ValueError("At least one Agent evaluation case is required.")
    results: list[AgentCaseEvaluation] = []
    for case in cases:
        started = timer()
        try:
            run = runner.run(case.prompt)
            duration_ms = max(0.0, (timer() - started) * 1000)
            results.append(
                _score_completed_run(
                    case,
                    final_answer=run.final_answer,
                    model_turns=run.model_turns,
                    messages=run.messages,
                    tool_successes=[result.success for result in run.tool_results],
                    tool_error_codes=[
                        result.error_code
                        for result in run.tool_results
                        if result.error_code is not None
                    ],
                    duration_ms=duration_ms,
                )
            )
        except AgentMaxTurnsError as error:
            duration_ms = max(0.0, (timer() - started) * 1000)
            tool_names, duplicate_count = _tool_trace(error.messages)
            results.append(
                _runtime_failure(
                    case,
                    duration_ms=duration_ms,
                    model_turns=error.model_turns,
                    tool_names=tool_names,
                    duplicate_count=duplicate_count,
                    runtime_error=str(error),
                )
            )
        except AgentProtocolError as error:
            duration_ms = max(0.0, (timer() - started) * 1000)
            results.append(
                _runtime_failure(
                    case,
                    duration_ms=duration_ms,
                    model_turns=1,
                    tool_names=[],
                    duplicate_count=0,
                    runtime_error=str(error),
                )
            )
    return _aggregate(provider, model_name, results)


def _score_completed_run(
    case: AgentEvaluationCase,
    *,
    final_answer: str,
    model_turns: int,
    messages: Sequence[object],
    tool_successes: list[bool],
    tool_error_codes: list[str],
    duration_ms: float,
) -> AgentCaseEvaluation:
    tool_names, duplicate_count = _tool_trace(messages)
    required_present = set(case.required_tools) & set(tool_names)
    required_recall = (
        len(required_present) / len(case.required_tools) if case.required_tools else 1.0
    )
    forbidden_count = sum(name in case.forbidden_tools for name in tool_names)
    normalized_answer = final_answer.casefold()
    missing_answers = [
        requirement
        for requirement in case.required_answer_contains
        if requirement.casefold() not in normalized_answer
    ]
    observed_errors = set(tool_error_codes)
    missing_errors = [
        code for code in case.expected_tool_error_codes if code not in observed_errors
    ]
    success_rate = sum(tool_successes) / len(tool_successes) if tool_successes else 1.0
    ideal_calls = len(case.required_tools)
    actual_calls = len(tool_names)
    if actual_calls == 0:
        step_efficiency = 1.0 if ideal_calls == 0 else 0.0
    else:
        step_efficiency = min(1.0, ideal_calls / actual_calls)
    common_pass = (
        required_recall == 1.0
        and forbidden_count == 0
        and not missing_answers
        and model_turns <= case.max_model_turns
        and actual_calls <= case.max_tool_calls
        and (case.allow_duplicate_tool_calls or duplicate_count == 0)
    )
    if case.expected_outcome is ExpectedTaskOutcome.COMPLETED:
        passed = common_pass and success_rate == 1.0
        observed = (
            ObservedTaskOutcome.COMPLETED if passed else ObservedTaskOutcome.FAILED
        )
    else:
        passed = common_pass and not missing_errors and bool(tool_error_codes)
        observed = (
            ObservedTaskOutcome.CORRECT_FAILURE
            if passed
            else ObservedTaskOutcome.FAILED
        )
    return AgentCaseEvaluation(
        case_id=case.case_id,
        passed=passed,
        expected_outcome=case.expected_outcome,
        observed_outcome=observed,
        duration_ms=duration_ms,
        model_turns=model_turns,
        tool_call_count=actual_calls,
        tool_names=tool_names,
        required_tool_recall=required_recall,
        tool_call_success_rate=success_rate,
        step_efficiency=step_efficiency,
        forbidden_tool_call_count=forbidden_count,
        duplicate_tool_call_count=duplicate_count,
        missing_answer_requirements=missing_answers,
        missing_expected_error_codes=missing_errors,
    )


def _runtime_failure(
    case: AgentEvaluationCase,
    *,
    duration_ms: float,
    model_turns: int,
    tool_names: list[str],
    duplicate_count: int,
    runtime_error: str,
) -> AgentCaseEvaluation:
    required_present = set(case.required_tools) & set(tool_names)
    recall = (
        len(required_present) / len(case.required_tools) if case.required_tools else 1.0
    )
    return AgentCaseEvaluation(
        case_id=case.case_id,
        passed=False,
        expected_outcome=case.expected_outcome,
        observed_outcome=ObservedTaskOutcome.FAILED,
        duration_ms=duration_ms,
        model_turns=model_turns,
        tool_call_count=len(tool_names),
        tool_names=tool_names,
        required_tool_recall=recall,
        tool_call_success_rate=0.0,
        step_efficiency=0.0,
        forbidden_tool_call_count=sum(
            name in case.forbidden_tools for name in tool_names
        ),
        duplicate_tool_call_count=duplicate_count,
        missing_answer_requirements=case.required_answer_contains,
        missing_expected_error_codes=case.expected_tool_error_codes,
        runtime_error=runtime_error,
    )


def _tool_trace(messages: Sequence[object]) -> tuple[list[str], int]:
    names: list[str] = []
    signatures: list[str] = []
    for message in messages:
        tool_calls = getattr(message, "tool_calls", [])
        for call in tool_calls:
            names.append(call.name)
            signatures.append(
                json.dumps(
                    {"name": call.name, "arguments": call.arguments},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
    duplicate_count = len(signatures) - len(set(signatures))
    return names, duplicate_count


def _aggregate(
    provider: str,
    model_name: str,
    results: list[AgentCaseEvaluation],
) -> AgentEvaluationResult:
    count = len(results)
    total_calls = sum(result.tool_call_count for result in results)
    total_successful_calls = sum(
        result.tool_call_success_rate * result.tool_call_count for result in results
    )
    total_duplicates = sum(result.duplicate_tool_call_count for result in results)
    recovery_cases = [
        result
        for result in results
        if result.expected_outcome is ExpectedTaskOutcome.CORRECT_FAILURE
    ]
    return AgentEvaluationResult(
        provider=provider,
        model_name=model_name,
        case_count=count,
        task_success_rate=sum(result.passed for result in results) / count,
        completed_rate=(
            sum(
                result.observed_outcome is ObservedTaskOutcome.COMPLETED
                for result in results
            )
            / count
        ),
        correct_failure_rate=(
            sum(
                result.observed_outcome is ObservedTaskOutcome.CORRECT_FAILURE
                for result in results
            )
            / count
        ),
        error_recovery_rate=(
            sum(result.passed for result in recovery_cases) / len(recovery_cases)
            if recovery_cases
            else 0.0
        ),
        mean_required_tool_recall=(
            sum(result.required_tool_recall for result in results) / count
        ),
        tool_call_success_rate=(
            total_successful_calls / total_calls if total_calls else 1.0
        ),
        forbidden_tool_violation_rate=(
            sum(result.forbidden_tool_call_count > 0 for result in results) / count
        ),
        duplicate_tool_call_rate=(
            total_duplicates / total_calls if total_calls else 0.0
        ),
        mean_step_efficiency=(
            sum(result.step_efficiency for result in results) / count
        ),
        mean_model_turns=sum(result.model_turns for result in results) / count,
        mean_tool_calls=total_calls / count,
        total_duration_ms=sum(result.duration_ms for result in results),
        cases=results,
    )

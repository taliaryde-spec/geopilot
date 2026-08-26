"""Command-line interface for GeoPilot."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from geopilot.agent import (
    AgentMaxTurnsError,
    AgentProtocolError,
    AgentRunner,
    ModelConfigurationError,
    ModelProvider,
    ModelRequestError,
    ModelResponseError,
    ModelSettings,
    build_model,
)
from geopilot.agent.tool_adapters import build_default_tool_registry
from geopilot.planning.store import PlanStore, PlanStoreError
from geopilot.tools.csv_point_loader import CsvPointLoadError
from geopilot.workflows.dataset_intake import inspect_and_validate_dataset

EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 3
EXIT_VALIDATION_ERROR = 4
EXIT_INPUT_ERROR = 5
EXIT_CONFIGURATION_ERROR = 6
EXIT_MODEL_ERROR = 7
EXIT_AGENT_ERROR = 8
EXIT_PLAN_ERROR = 9


def build_parser() -> argparse.ArgumentParser:
    """Build the GeoPilot command-line parser."""
    parser = argparse.ArgumentParser(
        prog="geopilot",
        description="Inspect and analyze geospatial datasets with GeoPilot.",
    )
    subparsers = parser.add_subparsers(dest="command")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect and validate a vector dataset or coordinate CSV.",
    )
    inspect_parser.add_argument(
        "source",
        type=Path,
        help="Path to GeoJSON, Shapefile, or a coordinate CSV.",
    )
    inspect_parser.add_argument(
        "--longitude-column",
        default="longitude",
        help="CSV longitude column name (default: longitude).",
    )
    inspect_parser.add_argument(
        "--latitude-column",
        default="latitude",
        help="CSV latitude column name (default: latitude).",
    )

    agent_parser = subparsers.add_parser(
        "agent",
        help="Run a natural-language GIS task with a real language model.",
    )
    agent_parser.add_argument(
        "prompt",
        help="Natural-language GIS task for GeoPilot.",
    )
    agent_parser.add_argument(
        "--provider",
        choices=[provider.value for provider in ModelProvider],
        default=None,
        help="Override GEOPILOT_PROVIDER for this run.",
    )
    agent_parser.add_argument(
        "--model",
        default=None,
        help="Override GEOPILOT_MODEL for this run.",
    )
    agent_parser.add_argument(
        "--base-url",
        default=None,
        help="Override GEOPILOT_BASE_URL for this run.",
    )
    agent_parser.add_argument(
        "--max-turns",
        type=int,
        default=6,
        help="Maximum model turns before the Agent stops (default: 6).",
    )
    agent_parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help=(
            "Override GEOPILOT_MODEL_MAX_OUTPUT_TOKENS for this run (default: 4096)."
        ),
    )

    show_plan_parser = subparsers.add_parser(
        "show-plan",
        help="Show a persisted analysis plan before making a decision.",
    )
    show_plan_parser.add_argument("plan_id", help="Plan identifier to display.")
    _add_plans_directory_argument(show_plan_parser)

    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve a pending analysis plan without executing it.",
    )
    approve_parser.add_argument("plan_id", help="Plan identifier to approve.")
    _add_plans_directory_argument(approve_parser)

    reject_parser = subparsers.add_parser(
        "reject",
        help="Reject a pending analysis plan with a reason.",
    )
    reject_parser.add_argument("plan_id", help="Plan identifier to reject.")
    reject_parser.add_argument(
        "--reason",
        required=True,
        help="Human-readable reason for rejecting the plan.",
    )
    _add_plans_directory_argument(reject_parser)
    return parser


def _add_plans_directory_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared local plan-checkpoint directory option."""
    parser.add_argument(
        "--plans-dir",
        type=Path,
        default=Path("artifacts") / "plans",
        help="Plan checkpoint directory (default: artifacts/plans).",
    )


def _run_inspect(
    source: Path,
    *,
    longitude_column: str,
    latitude_column: str,
) -> int:
    """Run dataset intake and print a structured JSON result."""
    try:
        result = inspect_and_validate_dataset(
            source,
            longitude_column=longitude_column,
            latitude_column=latitude_column,
        )
    except FileNotFoundError as error:
        payload = {
            "error": {
                "code": "dataset_not_found",
                "message": str(error),
            }
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_FILE_NOT_FOUND
    except CsvPointLoadError as error:
        error_payload: dict[str, object] = {
            "code": error.code.value,
            "message": str(error),
        }
        if error.field is not None:
            error_payload["field"] = error.field
        if error.count is not None:
            error_payload["count"] = error.count
        if error.row_numbers:
            error_payload["row_numbers"] = error.row_numbers

        payload = {"error": error_payload}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_INPUT_ERROR

    print(result.model_dump_json(indent=2))
    if result.validation.can_proceed:
        return EXIT_SUCCESS
    return EXIT_VALIDATION_ERROR


def _print_error(code: str, message: str) -> None:
    """Write one stable JSON error payload to standard error."""
    payload = {"error": {"code": code, "message": message}}
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)


def _print_max_turns_error(error: AgentMaxTurnsError) -> None:
    """Print a bounded tool trace without exposing full prompts or outputs."""
    payload = {
        "error": {
            "code": "agent_max_turns",
            "message": str(error),
        },
        "trace": {
            "model_turns": error.model_turns,
            "tool_results": [
                {
                    "name": result.name,
                    "success": result.success,
                    "error_code": result.error_code,
                    "error": result.error,
                }
                for result in error.tool_results
            ],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)


def _run_agent(
    prompt: str,
    *,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    max_turns: int,
    max_output_tokens: int | None,
) -> int:
    """Run the real-model Agent command and print its final answer."""
    try:
        settings = ModelSettings.from_environment(
            provider=provider,
            model=model,
            base_url=base_url,
            max_output_tokens=max_output_tokens,
        )
        runner = AgentRunner(
            build_model(settings),
            build_default_tool_registry(),
            max_model_turns=max_turns,
        )
        result = runner.run(prompt)
    except ModelConfigurationError as error:
        _print_error("model_configuration_error", str(error))
        return EXIT_CONFIGURATION_ERROR
    except ModelRequestError as error:
        _print_error(error.code, str(error))
        return EXIT_MODEL_ERROR
    except AgentMaxTurnsError as error:
        _print_max_turns_error(error)
        return EXIT_AGENT_ERROR
    except (AgentProtocolError, ModelResponseError) as error:
        _print_error("agent_runtime_error", str(error))
        return EXIT_AGENT_ERROR
    except ValueError as error:
        _print_error("invalid_agent_input", str(error))
        return EXIT_INPUT_ERROR

    print(result.final_answer)
    return EXIT_SUCCESS


def _run_show_plan(plan_id: str, plans_dir: Path) -> int:
    """Print one persisted plan for human review."""
    try:
        plan = PlanStore(plans_dir).load(plan_id)
    except PlanStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_PLAN_ERROR

    print(plan.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_approve_plan(plan_id: str, plans_dir: Path) -> int:
    """Persist an explicit human approval decision."""
    try:
        plan = PlanStore(plans_dir).approve(plan_id)
    except PlanStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_PLAN_ERROR

    print(plan.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_reject_plan(plan_id: str, reason: str, plans_dir: Path) -> int:
    """Persist an explicit human rejection decision."""
    try:
        plan = PlanStore(plans_dir).reject(plan_id, reason)
    except PlanStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_PLAN_ERROR
    except ValueError as error:
        _print_error("invalid_rejection_reason", str(error))
        return EXIT_PLAN_ERROR

    print(plan.model_dump_json(indent=2))
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    """Run the GeoPilot command-line entry point."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "inspect":
        return _run_inspect(
            arguments.source,
            longitude_column=arguments.longitude_column,
            latitude_column=arguments.latitude_column,
        )
    if arguments.command == "agent":
        return _run_agent(
            arguments.prompt,
            provider=arguments.provider,
            model=arguments.model,
            base_url=arguments.base_url,
            max_turns=arguments.max_turns,
            max_output_tokens=arguments.max_output_tokens,
        )
    if arguments.command == "show-plan":
        return _run_show_plan(arguments.plan_id, arguments.plans_dir)
    if arguments.command == "approve":
        return _run_approve_plan(arguments.plan_id, arguments.plans_dir)
    if arguments.command == "reject":
        return _run_reject_plan(
            arguments.plan_id,
            arguments.reason,
            arguments.plans_dir,
        )

    parser.print_help()
    return EXIT_SUCCESS

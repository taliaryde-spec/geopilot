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
from geopilot.execution import (
    ApprovedPlanExecutor,
    ExecutionStatus,
    PlanCompilationError,
    RunExecutionError,
    RunStore,
    RunStoreError,
)
from geopilot.planning.store import PlanStore, PlanStoreError
from geopilot.rag import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNKING_VARIANTS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_KNOWLEDGE_INDEX,
    DEFAULT_MODEL_CACHE,
    DEFAULT_TOKEN_WARNING_RATIO,
    ChunkingExperimentVariant,
    EmbeddingError,
    KnowledgeLoadError,
    VectorStoreError,
    build_knowledge_index,
    evaluate_retrieval,
    load_evaluation_cases,
    open_knowledge_retriever,
    run_chunking_experiment,
)
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
EXIT_EXECUTION_ERROR = 10
EXIT_RAG_ERROR = 11


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
        "--knowledge-index",
        type=Path,
        default=DEFAULT_KNOWLEDGE_INDEX,
        help="Optional local RAG index (default: artifacts/rag/index.json).",
    )
    agent_parser.add_argument(
        "--model-cache",
        type=Path,
        default=DEFAULT_MODEL_CACHE,
        help="Local FastEmbed model cache directory.",
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

    execute_parser = subparsers.add_parser(
        "execute",
        help="Execute a new run from an approved analysis plan.",
    )
    execute_parser.add_argument("plan_id", help="Approved plan identifier.")
    _add_plans_directory_argument(execute_parser)
    _add_runs_directory_argument(execute_parser)

    show_run_parser = subparsers.add_parser(
        "show-run",
        help="Show a persisted execution checkpoint.",
    )
    show_run_parser.add_argument("run_id", help="Execution run identifier.")
    _add_runs_directory_argument(show_run_parser)

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume the first incomplete step of an execution run.",
    )
    resume_parser.add_argument("run_id", help="Execution run identifier.")
    _add_plans_directory_argument(resume_parser)
    _add_runs_directory_argument(resume_parser)

    rag_build_parser = subparsers.add_parser(
        "rag-build",
        help="Load, chunk, embed, and persist local knowledge documents.",
    )
    rag_build_parser.add_argument(
        "sources",
        nargs="+",
        type=Path,
        help="Markdown/text files or directories to index.",
    )
    _add_rag_index_arguments(rag_build_parser, include_model=True)
    rag_build_parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
    )
    rag_build_parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP,
    )

    rag_search_parser = subparsers.add_parser(
        "rag-search",
        help="Search the local knowledge vector index with citations.",
    )
    rag_search_parser.add_argument("query", help="Knowledge retrieval query.")
    _add_rag_index_arguments(rag_search_parser, include_model=False)
    rag_search_parser.add_argument("--top-k", type=int, default=4)

    rag_evaluate_parser = subparsers.add_parser(
        "rag-evaluate",
        help="Evaluate retrieval coverage, precision, and ranking quality.",
    )
    rag_evaluate_parser.add_argument(
        "cases",
        type=Path,
        help="JSON retrieval evaluation cases.",
    )
    _add_rag_index_arguments(rag_evaluate_parser, include_model=False)
    rag_evaluate_parser.add_argument("--top-k", type=int, default=4)

    chunk_experiment_parser = subparsers.add_parser(
        "rag-chunk-experiment",
        help="Compare chunk size and overlap variants under fixed RAG settings.",
    )
    chunk_experiment_parser.add_argument(
        "sources",
        nargs="+",
        type=Path,
        help="Markdown/text files or directories shared by every variant.",
    )
    chunk_experiment_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("knowledge") / "retrieval_cases.json",
        help="Shared JSON retrieval gold set.",
    )
    chunk_experiment_parser.add_argument(
        "--variant",
        action="append",
        dest="variants",
        type=_parse_chunking_variant,
        help="Repeatable SIZE:OVERLAP pair; defaults to four built-in variants.",
    )
    chunk_experiment_parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("artifacts") / "rag" / "chunk_experiments",
        help="Directory for per-variant vector indices.",
    )
    chunk_experiment_parser.add_argument(
        "--model-cache",
        type=Path,
        default=DEFAULT_MODEL_CACHE,
        help="Local FastEmbed model cache directory.",
    )
    chunk_experiment_parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"Embedding model shared by variants (default: {DEFAULT_EMBEDDING_MODEL}).",
    )
    chunk_experiment_parser.add_argument("--top-k", type=int, default=3)
    chunk_experiment_parser.add_argument(
        "--token-warning-ratio",
        type=float,
        default=DEFAULT_TOKEN_WARNING_RATIO,
        help="Flag chunks at or above this share of the model token limit.",
    )
    return parser


def _parse_chunking_variant(value: str) -> ChunkingExperimentVariant:
    """Parse a CLI SIZE:OVERLAP pair into a validated experiment variant."""
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("variant must use SIZE:OVERLAP format")
    try:
        return ChunkingExperimentVariant(
            chunk_size=int(parts[0]),
            chunk_overlap=int(parts[1]),
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _add_plans_directory_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared local plan-checkpoint directory option."""
    parser.add_argument(
        "--plans-dir",
        type=Path,
        default=Path("artifacts") / "plans",
        help="Plan checkpoint directory (default: artifacts/plans).",
    )


def _add_runs_directory_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared execution-checkpoint directory option."""
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("artifacts") / "runs",
        help="Execution checkpoint directory (default: artifacts/runs).",
    )


def _add_rag_index_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_model: bool,
) -> None:
    """Add shared local knowledge index and model cache options."""
    parser.add_argument(
        "--index-path",
        type=Path,
        default=DEFAULT_KNOWLEDGE_INDEX,
        help="Local vector index path (default: artifacts/rag/index.json).",
    )
    parser.add_argument(
        "--model-cache",
        type=Path,
        default=DEFAULT_MODEL_CACHE,
        help="Local FastEmbed model cache directory.",
    )
    if include_model:
        parser.add_argument(
            "--embedding-model",
            default=DEFAULT_EMBEDDING_MODEL,
            help=f"Embedding model (default: {DEFAULT_EMBEDDING_MODEL}).",
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
    knowledge_index: Path,
    model_cache: Path,
) -> int:
    """Run the real-model Agent command and print its final answer."""
    try:
        settings = ModelSettings.from_environment(
            provider=provider,
            model=model,
            base_url=base_url,
            max_output_tokens=max_output_tokens,
        )
        knowledge_retriever = (
            open_knowledge_retriever(
                index_path=knowledge_index,
                cache_directory=model_cache,
            )
            if knowledge_index.is_file()
            else None
        )
        runner = AgentRunner(
            build_model(settings),
            build_default_tool_registry(knowledge_retriever=knowledge_retriever),
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
    except (EmbeddingError, VectorStoreError) as error:
        _print_error(error.code.value, str(error))
        return EXIT_RAG_ERROR
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


def _run_execute_plan(plan_id: str, plans_dir: Path, runs_dir: Path) -> int:
    """Execute an approved plan and print its durable run checkpoint."""
    try:
        run = ApprovedPlanExecutor(
            PlanStore(plans_dir),
            RunStore(runs_dir),
        ).execute(plan_id)
    except PlanStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_PLAN_ERROR
    except (PlanCompilationError, RunStoreError, RunExecutionError) as error:
        _print_error(error.code.value, str(error))
        return EXIT_EXECUTION_ERROR

    print(run.model_dump_json(indent=2))
    if run.status is ExecutionStatus.SUCCEEDED:
        return EXIT_SUCCESS
    return EXIT_EXECUTION_ERROR


def _run_show_run(run_id: str, runs_dir: Path) -> int:
    """Print one persisted execution checkpoint."""
    try:
        run = RunStore(runs_dir).load(run_id)
    except RunStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_EXECUTION_ERROR
    print(run.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_resume(run_id: str, plans_dir: Path, runs_dir: Path) -> int:
    """Resume a failed or interrupted execution run."""
    try:
        run = ApprovedPlanExecutor(
            PlanStore(plans_dir),
            RunStore(runs_dir),
        ).resume(run_id)
    except (RunStoreError, RunExecutionError) as error:
        _print_error(error.code.value, str(error))
        return EXIT_EXECUTION_ERROR
    print(run.model_dump_json(indent=2))
    if run.status is ExecutionStatus.SUCCEEDED:
        return EXIT_SUCCESS
    return EXIT_EXECUTION_ERROR


def _rag_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    value = getattr(code, "value", None)
    return str(value) if isinstance(value, str) else "rag_runtime_error"


def _run_rag_build(
    sources: list[Path],
    *,
    index_path: Path,
    model_cache: Path,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> int:
    """Build a local vector index and print its manifest summary."""
    try:
        result = build_knowledge_index(
            sources,
            index_path=index_path,
            model_name=embedding_model,
            cache_directory=model_cache,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            working_directory=Path.cwd(),
        )
    except (
        KnowledgeLoadError,
        EmbeddingError,
        VectorStoreError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        _print_error(_rag_error_code(error), str(error))
        return EXIT_RAG_ERROR
    print(result.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_rag_search(
    query: str,
    *,
    index_path: Path,
    model_cache: Path,
    top_k: int,
) -> int:
    """Query a local vector index and print ranked citation evidence."""
    try:
        result = open_knowledge_retriever(
            index_path=index_path,
            cache_directory=model_cache,
        ).search(query, top_k=top_k)
    except (
        EmbeddingError,
        VectorStoreError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        _print_error(_rag_error_code(error), str(error))
        return EXIT_RAG_ERROR
    print(result.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_rag_evaluate(
    cases_path: Path,
    *,
    index_path: Path,
    model_cache: Path,
    top_k: int,
) -> int:
    """Run an offline retrieval evaluation against the local index."""
    try:
        retriever = open_knowledge_retriever(
            index_path=index_path,
            cache_directory=model_cache,
        )
        result = evaluate_retrieval(
            retriever,
            load_evaluation_cases(cases_path),
            top_k=top_k,
        )
    except (
        EmbeddingError,
        VectorStoreError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        _print_error(_rag_error_code(error), str(error))
        return EXIT_RAG_ERROR
    print(result.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_rag_chunk_experiment(
    sources: list[Path],
    *,
    cases_path: Path,
    variants: list[ChunkingExperimentVariant] | None,
    output_directory: Path,
    model_cache: Path,
    embedding_model: str,
    top_k: int,
    token_warning_ratio: float,
) -> int:
    """Compare chunking variants and print all build and retrieval metrics."""
    try:
        result = run_chunking_experiment(
            sources,
            load_evaluation_cases(cases_path),
            variants=variants or DEFAULT_CHUNKING_VARIANTS,
            output_directory=output_directory,
            model_name=embedding_model,
            cache_directory=model_cache,
            top_k=top_k,
            token_warning_ratio=token_warning_ratio,
            working_directory=Path.cwd(),
        )
    except (
        KnowledgeLoadError,
        EmbeddingError,
        VectorStoreError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        _print_error(_rag_error_code(error), str(error))
        return EXIT_RAG_ERROR
    print(result.model_dump_json(indent=2))
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
            knowledge_index=arguments.knowledge_index,
            model_cache=arguments.model_cache,
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
    if arguments.command == "execute":
        return _run_execute_plan(
            arguments.plan_id,
            arguments.plans_dir,
            arguments.runs_dir,
        )
    if arguments.command == "show-run":
        return _run_show_run(arguments.run_id, arguments.runs_dir)
    if arguments.command == "resume":
        return _run_resume(
            arguments.run_id,
            arguments.plans_dir,
            arguments.runs_dir,
        )
    if arguments.command == "rag-build":
        return _run_rag_build(
            arguments.sources,
            index_path=arguments.index_path,
            model_cache=arguments.model_cache,
            embedding_model=arguments.embedding_model,
            chunk_size=arguments.chunk_size,
            chunk_overlap=arguments.chunk_overlap,
        )
    if arguments.command == "rag-search":
        return _run_rag_search(
            arguments.query,
            index_path=arguments.index_path,
            model_cache=arguments.model_cache,
            top_k=arguments.top_k,
        )
    if arguments.command == "rag-evaluate":
        return _run_rag_evaluate(
            arguments.cases,
            index_path=arguments.index_path,
            model_cache=arguments.model_cache,
            top_k=arguments.top_k,
        )
    if arguments.command == "rag-chunk-experiment":
        return _run_rag_chunk_experiment(
            arguments.sources,
            cases_path=arguments.cases,
            variants=arguments.variants,
            output_directory=arguments.output_directory,
            model_cache=arguments.model_cache,
            embedding_model=arguments.embedding_model,
            top_k=arguments.top_k,
            token_warning_ratio=arguments.token_warning_ratio,
        )

    parser.print_help()
    return EXIT_SUCCESS

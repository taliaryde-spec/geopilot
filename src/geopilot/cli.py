"""Command-line interface for GeoPilot."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

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
from geopilot.agent.models import ToolResult
from geopilot.agent.tool_adapters import build_default_tool_registry
from geopilot.evaluation import evaluate_agent, load_agent_evaluation_cases
from geopilot.execution import (
    ApprovedPlanExecutor,
    ExecutionStatus,
    PlanCompilationError,
    RunExecutionError,
    RunStore,
    RunStoreError,
)
from geopilot.memory import (
    DEFAULT_MEMORY_PATH,
    MemoryContextBuilder,
    MemoryKind,
    MemoryStore,
    MemoryStoreError,
    MemoryWriteRequest,
)
from geopilot.observability import (
    DEFAULT_TRACE_PATH,
    AgentTraceStatus,
    TraceStore,
    TraceStoreError,
    build_agent_trace,
)
from geopilot.planning.store import PlanStore, PlanStoreError
from geopilot.rag import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNKING_VARIANTS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_HYBRID_CANDIDATE_K,
    DEFAULT_KNOWLEDGE_INDEX,
    DEFAULT_MODEL_CACHE,
    DEFAULT_RERANK_CANDIDATE_K,
    DEFAULT_RERANKER_CACHE,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RETRIEVAL_MODE,
    DEFAULT_RRF_K,
    DEFAULT_TOKEN_WARNING_RATIO,
    ChunkingExperimentVariant,
    EmbeddingError,
    KnowledgeLoadError,
    RetrievalMode,
    VectorStoreError,
    build_knowledge_index,
    evaluate_retrieval,
    load_evaluation_cases,
    open_knowledge_retriever,
    run_chunking_experiment,
    run_rerank_experiment,
    run_retrieval_experiment,
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
EXIT_MEMORY_ERROR = 12
EXIT_EVALUATION_ERROR = 13
EXIT_TRACE_ERROR = 14


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
    agent_parser.add_argument(
        "--memory-path",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="Local long-term memory JSON file.",
    )
    agent_parser.add_argument(
        "--memory-namespace",
        default="default",
        help="Isolated memory namespace used by this Agent run.",
    )
    agent_parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable long-term memory recall for this Agent run.",
    )
    agent_parser.add_argument(
        "--trace-path",
        type=Path,
        default=DEFAULT_TRACE_PATH,
        help="Append redacted run metadata to this local JSONL file.",
    )
    agent_parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable local redacted tracing for this Agent run.",
    )

    agent_evaluate_parser = subparsers.add_parser(
        "agent-evaluate",
        help="Evaluate Agent outcomes, tool use, efficiency, and safety.",
    )
    agent_evaluate_parser.add_argument(
        "cases",
        nargs="?",
        type=Path,
        default=Path("evals") / "agent_cases_v1.json",
        help="Version-controlled Agent gold cases.",
    )
    agent_evaluate_parser.add_argument(
        "--knowledge-index",
        type=Path,
        default=DEFAULT_KNOWLEDGE_INDEX,
        help="Optional local RAG index used by search_knowledge cases.",
    )
    agent_evaluate_parser.add_argument(
        "--model-cache",
        type=Path,
        default=DEFAULT_MODEL_CACHE,
        help="Local FastEmbed model cache directory.",
    )
    agent_evaluate_parser.add_argument(
        "--provider",
        choices=[provider.value for provider in ModelProvider],
        default=None,
        help="Override GEOPILOT_PROVIDER for this evaluation.",
    )
    agent_evaluate_parser.add_argument(
        "--model",
        default=None,
        help="Override GEOPILOT_MODEL for this evaluation.",
    )
    agent_evaluate_parser.add_argument(
        "--base-url",
        default=None,
        help="Override GEOPILOT_BASE_URL for this evaluation.",
    )
    agent_evaluate_parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="Override the model response token limit for this evaluation.",
    )
    agent_evaluate_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optionally persist the JSON result in addition to printing it.",
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

    memory_set_parser = subparsers.add_parser(
        "memory-set",
        help="Create or update one explicitly confirmed long-term memory.",
    )
    memory_set_parser.add_argument("kind", type=MemoryKind, choices=list(MemoryKind))
    memory_set_parser.add_argument("key", help="Stable snake_case memory key.")
    memory_set_parser.add_argument(
        "value", help="Confirmed value; never store secrets."
    )
    memory_set_parser.add_argument(
        "--confirmed",
        action="store_true",
        help="Required acknowledgement that the user authorized this write.",
    )
    memory_set_parser.add_argument("--expires-in-days", type=int, default=None)
    _add_memory_storage_arguments(memory_set_parser)

    memory_list_parser = subparsers.add_parser(
        "memory-list",
        help="List active long-term memories in one namespace.",
    )
    memory_list_parser.add_argument("--kind", type=MemoryKind, choices=list(MemoryKind))
    memory_list_parser.add_argument("--include-expired", action="store_true")
    _add_memory_storage_arguments(memory_list_parser)

    memory_recall_parser = subparsers.add_parser(
        "memory-recall",
        help="Preview memories selected for a task without calling an LLM.",
    )
    memory_recall_parser.add_argument("query", help="Current task used for filtering.")
    memory_recall_parser.add_argument("--top-k", type=int, default=6)
    memory_recall_parser.add_argument("--max-characters", type=int, default=2000)
    _add_memory_storage_arguments(memory_recall_parser)

    memory_delete_parser = subparsers.add_parser(
        "memory-delete",
        help="Delete exactly one long-term memory from its namespace.",
    )
    memory_delete_parser.add_argument("memory_id", help="Memory identifier to delete.")
    _add_memory_storage_arguments(memory_delete_parser)

    trace_list_parser = subparsers.add_parser(
        "trace-list",
        help="List recent redacted Agent run traces, newest first.",
    )
    trace_list_parser.add_argument(
        "--trace-path",
        type=Path,
        default=DEFAULT_TRACE_PATH,
    )
    trace_list_parser.add_argument("--limit", type=int, default=20)
    trace_list_parser.add_argument(
        "--status",
        type=AgentTraceStatus,
        choices=list(AgentTraceStatus),
        default=None,
    )

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
    _add_retrieval_strategy_arguments(rag_search_parser)

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
    _add_retrieval_strategy_arguments(rag_evaluate_parser)

    retrieval_experiment_parser = subparsers.add_parser(
        "rag-retrieval-experiment",
        help="Compare Dense-only and BM25 + Dense Hybrid Search.",
    )
    retrieval_experiment_parser.add_argument(
        "cases",
        type=Path,
        help="JSON retrieval evaluation cases shared by both modes.",
    )
    _add_rag_index_arguments(retrieval_experiment_parser, include_model=False)
    retrieval_experiment_parser.add_argument("--top-k", type=int, default=3)
    retrieval_experiment_parser.add_argument(
        "--hybrid-candidate-k",
        type=int,
        default=DEFAULT_HYBRID_CANDIDATE_K,
    )
    retrieval_experiment_parser.add_argument(
        "--rrf-k",
        type=int,
        default=DEFAULT_RRF_K,
    )

    rerank_experiment_parser = subparsers.add_parser(
        "rag-rerank-experiment",
        help="Compare Hybrid Search and Cross-Encoder reranking.",
    )
    rerank_experiment_parser.add_argument(
        "cases",
        type=Path,
        help="JSON retrieval evaluation cases shared by both modes.",
    )
    _add_rag_index_arguments(rerank_experiment_parser, include_model=False)
    rerank_experiment_parser.add_argument("--top-k", type=int, default=3)
    rerank_experiment_parser.add_argument(
        "--hybrid-candidate-k",
        type=int,
        default=DEFAULT_HYBRID_CANDIDATE_K,
    )
    rerank_experiment_parser.add_argument(
        "--rrf-k",
        type=int,
        default=DEFAULT_RRF_K,
    )
    _add_reranker_arguments(rerank_experiment_parser)

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


def _add_retrieval_strategy_arguments(parser: argparse.ArgumentParser) -> None:
    """Add retrieval selection plus Hybrid and Rerank tuning parameters."""
    parser.add_argument(
        "--retrieval-mode",
        type=RetrievalMode,
        choices=list(RetrievalMode),
        default=DEFAULT_RETRIEVAL_MODE,
    )
    parser.add_argument(
        "--hybrid-candidate-k",
        type=int,
        default=DEFAULT_HYBRID_CANDIDATE_K,
    )
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)
    _add_reranker_arguments(parser)


def _add_reranker_arguments(parser: argparse.ArgumentParser) -> None:
    """Add opt-in Cross-Encoder model, cache, and candidate-pool settings."""
    parser.add_argument(
        "--reranker-model",
        default=DEFAULT_RERANKER_MODEL,
    )
    parser.add_argument(
        "--reranker-cache",
        type=Path,
        default=DEFAULT_RERANKER_CACHE,
    )
    parser.add_argument(
        "--rerank-candidate-k",
        type=int,
        default=DEFAULT_RERANK_CANDIDATE_K,
    )


def _add_plans_directory_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared local plan-checkpoint directory option."""
    parser.add_argument(
        "--plans-dir",
        type=Path,
        default=Path("artifacts") / "plans",
        help="Plan checkpoint directory (default: artifacts/plans).",
    )


def _add_memory_storage_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared memory file and namespace isolation options."""
    parser.add_argument(
        "--memory-path",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
    )
    parser.add_argument("--namespace", default="default")


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


def _print_warning(code: str, message: str) -> None:
    """Write one non-fatal structured warning to standard error."""
    payload = {"warning": {"code": code, "message": message}}
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
    memory_path: Path,
    memory_namespace: str,
    memory_enabled: bool,
    trace_path: Path,
    trace_enabled: bool,
) -> int:
    """Run the real-model Agent command and print its final answer."""
    started = perf_counter()
    settings: ModelSettings | None = None
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
        memory_context = (
            MemoryContextBuilder(MemoryStore(memory_path))
            .recall(prompt, memory_namespace)
            .context
            if memory_enabled
            else None
        )
        runner = AgentRunner(
            build_model(settings),
            build_default_tool_registry(knowledge_retriever=knowledge_retriever),
            max_model_turns=max_turns,
        )
        result = runner.run(prompt, memory_context=memory_context)
    except ModelConfigurationError as error:
        _print_error("model_configuration_error", str(error))
        return EXIT_CONFIGURATION_ERROR
    except ModelRequestError as error:
        _persist_agent_trace(
            prompt,
            settings=settings,
            trace_path=trace_path,
            trace_enabled=trace_enabled,
            started=started,
            status=AgentTraceStatus.FAILED,
            error_code=error.code,
        )
        _print_error(error.code, str(error))
        return EXIT_MODEL_ERROR
    except AgentMaxTurnsError as error:
        _persist_agent_trace(
            prompt,
            settings=settings,
            trace_path=trace_path,
            trace_enabled=trace_enabled,
            started=started,
            status=AgentTraceStatus.FAILED,
            model_turns=error.model_turns,
            tool_results=error.tool_results,
            error_code="agent_max_turns",
        )
        _print_max_turns_error(error)
        return EXIT_AGENT_ERROR
    except (AgentProtocolError, ModelResponseError) as error:
        _persist_agent_trace(
            prompt,
            settings=settings,
            trace_path=trace_path,
            trace_enabled=trace_enabled,
            started=started,
            status=AgentTraceStatus.FAILED,
            error_code="agent_runtime_error",
        )
        _print_error("agent_runtime_error", str(error))
        return EXIT_AGENT_ERROR
    except (EmbeddingError, VectorStoreError) as error:
        _persist_agent_trace(
            prompt,
            settings=settings,
            trace_path=trace_path,
            trace_enabled=trace_enabled,
            started=started,
            status=AgentTraceStatus.FAILED,
            error_code=error.code.value,
        )
        _print_error(error.code.value, str(error))
        return EXIT_RAG_ERROR
    except MemoryStoreError as error:
        _persist_agent_trace(
            prompt,
            settings=settings,
            trace_path=trace_path,
            trace_enabled=trace_enabled,
            started=started,
            status=AgentTraceStatus.FAILED,
            error_code=error.code.value,
        )
        _print_error(error.code.value, str(error))
        return EXIT_MEMORY_ERROR
    except ValueError as error:
        _persist_agent_trace(
            prompt,
            settings=settings,
            trace_path=trace_path,
            trace_enabled=trace_enabled,
            started=started,
            status=AgentTraceStatus.FAILED,
            error_code="invalid_agent_input",
        )
        _print_error("invalid_agent_input", str(error))
        return EXIT_INPUT_ERROR

    _persist_agent_trace(
        prompt,
        settings=settings,
        trace_path=trace_path,
        trace_enabled=trace_enabled,
        started=started,
        status=AgentTraceStatus.SUCCEEDED,
        model_turns=result.model_turns,
        tool_results=result.tool_results,
        final_answer=result.final_answer,
    )
    print(result.final_answer)
    return EXIT_SUCCESS


def _persist_agent_trace(
    prompt: str,
    *,
    settings: ModelSettings | None,
    trace_path: Path,
    trace_enabled: bool,
    started: float,
    status: AgentTraceStatus,
    model_turns: int = 0,
    tool_results: Sequence[ToolResult] = (),
    final_answer: str | None = None,
    error_code: str | None = None,
) -> None:
    """Best-effort trace persistence that never changes the Agent outcome."""
    if not trace_enabled or settings is None:
        return
    try:
        TraceStore(trace_path).append(
            build_agent_trace(
                prompt,
                provider=settings.provider.value,
                model_name=settings.model,
                status=status,
                duration_ms=(perf_counter() - started) * 1000,
                model_turns=model_turns,
                tool_results=tool_results,
                final_answer=final_answer,
                error_code=error_code,
            )
        )
    except (TraceStoreError, OSError, ValueError) as error:
        _print_warning("trace_persistence_failed", str(error))


def _run_trace_list(
    *,
    trace_path: Path,
    limit: int,
    status: AgentTraceStatus | None,
) -> int:
    """Print a bounded, newest-first view of redacted Agent runs."""
    try:
        traces = TraceStore(trace_path).list_traces(limit=limit, status=status)
    except TraceStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_TRACE_ERROR
    except ValueError as error:
        _print_error("invalid_trace_query", str(error))
        return EXIT_TRACE_ERROR
    print(
        json.dumps(
            [trace.model_dump(mode="json") for trace in traces],
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_SUCCESS


def _run_agent_evaluate(
    cases_path: Path,
    *,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    max_output_tokens: int | None,
    knowledge_index: Path,
    model_cache: Path,
    output_path: Path | None,
) -> int:
    """Run a controlled real-model benchmark with long-term memory disabled."""
    try:
        cases = load_agent_evaluation_cases(cases_path)
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
        with TemporaryDirectory(prefix="geopilot-agent-eval-") as plan_directory:
            runner = AgentRunner(
                build_model(settings),
                build_default_tool_registry(
                    plan_store=PlanStore(Path(plan_directory)),
                    knowledge_retriever=knowledge_retriever,
                ),
                max_model_turns=max(case.max_model_turns for case in cases),
            )
            result = evaluate_agent(
                runner,
                cases,
                provider=settings.provider.value,
                model_name=settings.model,
            )
        payload = result.model_dump_json(indent=2)
        if output_path is not None:
            resolved_output = output_path.resolve()
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            resolved_output.write_text(f"{payload}\n", encoding="utf-8")
    except ModelConfigurationError as error:
        _print_error("model_configuration_error", str(error))
        return EXIT_CONFIGURATION_ERROR
    except ModelRequestError as error:
        _print_error(error.code, str(error))
        return EXIT_MODEL_ERROR
    except (ModelResponseError, AgentProtocolError) as error:
        _print_error("agent_evaluation_runtime_error", str(error))
        return EXIT_EVALUATION_ERROR
    except (EmbeddingError, VectorStoreError) as error:
        _print_error(error.code.value, str(error))
        return EXIT_RAG_ERROR
    except (OSError, RuntimeError, ValueError) as error:
        _print_error("invalid_agent_evaluation", str(error))
        return EXIT_EVALUATION_ERROR

    print(payload)
    return EXIT_SUCCESS


def _run_memory_set(
    kind: MemoryKind,
    key: str,
    value: str,
    *,
    memory_path: Path,
    namespace: str,
    confirmed: bool,
    expires_in_days: int | None,
) -> int:
    """Persist one user-confirmed memory and print its auditable metadata."""
    try:
        entry = MemoryStore(memory_path).upsert(
            MemoryWriteRequest(
                namespace=namespace,
                kind=kind,
                key=key,
                value=value,
                confirmed=confirmed,
                expires_in_days=expires_in_days,
            )
        )
    except MemoryStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_MEMORY_ERROR
    except (OSError, ValueError) as error:
        _print_error("invalid_memory_input", str(error))
        return EXIT_MEMORY_ERROR
    print(entry.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_memory_list(
    *,
    memory_path: Path,
    namespace: str,
    kind: MemoryKind | None,
    include_expired: bool,
) -> int:
    """List one namespace without exposing entries from another scope."""
    try:
        entries = MemoryStore(memory_path).list_entries(
            namespace,
            kind=kind,
            include_expired=include_expired,
        )
    except MemoryStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_MEMORY_ERROR
    except OSError as error:
        _print_error("memory_io_error", str(error))
        return EXIT_MEMORY_ERROR
    print(
        json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_SUCCESS


def _run_memory_recall(
    query: str,
    *,
    memory_path: Path,
    namespace: str,
    top_k: int,
    max_characters: int,
) -> int:
    """Preview deterministic memory selection and bounded prompt context."""
    try:
        result = MemoryContextBuilder(
            MemoryStore(memory_path),
            top_k=top_k,
            max_characters=max_characters,
        ).recall(query, namespace)
    except MemoryStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_MEMORY_ERROR
    except (OSError, ValueError) as error:
        _print_error("invalid_memory_input", str(error))
        return EXIT_MEMORY_ERROR
    print(result.model_dump_json(indent=2))
    return EXIT_SUCCESS


def _run_memory_delete(
    memory_id: str,
    *,
    memory_path: Path,
    namespace: str,
) -> int:
    """Delete one exact memory entry and return what was removed."""
    try:
        entry = MemoryStore(memory_path).delete(namespace, memory_id)
    except MemoryStoreError as error:
        _print_error(error.code.value, str(error))
        return EXIT_MEMORY_ERROR
    except OSError as error:
        _print_error("memory_io_error", str(error))
        return EXIT_MEMORY_ERROR
    print(entry.model_dump_json(indent=2))
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
    retrieval_mode: RetrievalMode,
    hybrid_candidate_k: int,
    rrf_k: int,
    reranker_model: str,
    reranker_cache: Path,
    rerank_candidate_k: int,
) -> int:
    """Query a local vector index and print ranked citation evidence."""
    try:
        result = open_knowledge_retriever(
            index_path=index_path,
            cache_directory=model_cache,
            retrieval_mode=retrieval_mode,
            hybrid_candidate_k=hybrid_candidate_k,
            rrf_k=rrf_k,
            reranker_model_name=reranker_model,
            reranker_cache_directory=reranker_cache,
            rerank_candidate_k=rerank_candidate_k,
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
    retrieval_mode: RetrievalMode,
    hybrid_candidate_k: int,
    rrf_k: int,
    reranker_model: str,
    reranker_cache: Path,
    rerank_candidate_k: int,
) -> int:
    """Run an offline retrieval evaluation against the local index."""
    try:
        retriever = open_knowledge_retriever(
            index_path=index_path,
            cache_directory=model_cache,
            retrieval_mode=retrieval_mode,
            hybrid_candidate_k=hybrid_candidate_k,
            rrf_k=rrf_k,
            reranker_model_name=reranker_model,
            reranker_cache_directory=reranker_cache,
            rerank_candidate_k=rerank_candidate_k,
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


def _run_rag_retrieval_experiment(
    cases_path: Path,
    *,
    index_path: Path,
    model_cache: Path,
    top_k: int,
    hybrid_candidate_k: int,
    rrf_k: int,
) -> int:
    """Compare Dense-only and Hybrid Search under shared settings."""
    try:
        result = run_retrieval_experiment(
            index_path,
            load_evaluation_cases(cases_path),
            cache_directory=model_cache,
            top_k=top_k,
            hybrid_candidate_k=hybrid_candidate_k,
            rrf_k=rrf_k,
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


def _run_rag_rerank_experiment(
    cases_path: Path,
    *,
    index_path: Path,
    model_cache: Path,
    top_k: int,
    hybrid_candidate_k: int,
    rrf_k: int,
    reranker_model: str,
    reranker_cache: Path,
    rerank_candidate_k: int,
) -> int:
    """Compare Hybrid Search and Cross-Encoder reranking under shared settings."""
    try:
        result = run_rerank_experiment(
            index_path,
            load_evaluation_cases(cases_path),
            cache_directory=model_cache,
            reranker_cache_directory=reranker_cache,
            reranker_model_name=reranker_model,
            top_k=top_k,
            hybrid_candidate_k=hybrid_candidate_k,
            rerank_candidate_k=rerank_candidate_k,
            rrf_k=rrf_k,
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
            memory_path=arguments.memory_path,
            memory_namespace=arguments.memory_namespace,
            memory_enabled=not arguments.no_memory,
            trace_path=arguments.trace_path,
            trace_enabled=not arguments.no_trace,
        )
    if arguments.command == "agent-evaluate":
        return _run_agent_evaluate(
            arguments.cases,
            provider=arguments.provider,
            model=arguments.model,
            base_url=arguments.base_url,
            max_output_tokens=arguments.max_output_tokens,
            knowledge_index=arguments.knowledge_index,
            model_cache=arguments.model_cache,
            output_path=arguments.output,
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
    if arguments.command == "memory-set":
        return _run_memory_set(
            arguments.kind,
            arguments.key,
            arguments.value,
            memory_path=arguments.memory_path,
            namespace=arguments.namespace,
            confirmed=arguments.confirmed,
            expires_in_days=arguments.expires_in_days,
        )
    if arguments.command == "memory-list":
        return _run_memory_list(
            memory_path=arguments.memory_path,
            namespace=arguments.namespace,
            kind=arguments.kind,
            include_expired=arguments.include_expired,
        )
    if arguments.command == "memory-recall":
        return _run_memory_recall(
            arguments.query,
            memory_path=arguments.memory_path,
            namespace=arguments.namespace,
            top_k=arguments.top_k,
            max_characters=arguments.max_characters,
        )
    if arguments.command == "memory-delete":
        return _run_memory_delete(
            arguments.memory_id,
            memory_path=arguments.memory_path,
            namespace=arguments.namespace,
        )
    if arguments.command == "trace-list":
        return _run_trace_list(
            trace_path=arguments.trace_path,
            limit=arguments.limit,
            status=arguments.status,
        )
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
            retrieval_mode=arguments.retrieval_mode,
            hybrid_candidate_k=arguments.hybrid_candidate_k,
            rrf_k=arguments.rrf_k,
            reranker_model=arguments.reranker_model,
            reranker_cache=arguments.reranker_cache,
            rerank_candidate_k=arguments.rerank_candidate_k,
        )
    if arguments.command == "rag-evaluate":
        return _run_rag_evaluate(
            arguments.cases,
            index_path=arguments.index_path,
            model_cache=arguments.model_cache,
            top_k=arguments.top_k,
            retrieval_mode=arguments.retrieval_mode,
            hybrid_candidate_k=arguments.hybrid_candidate_k,
            rrf_k=arguments.rrf_k,
            reranker_model=arguments.reranker_model,
            reranker_cache=arguments.reranker_cache,
            rerank_candidate_k=arguments.rerank_candidate_k,
        )
    if arguments.command == "rag-retrieval-experiment":
        return _run_rag_retrieval_experiment(
            arguments.cases,
            index_path=arguments.index_path,
            model_cache=arguments.model_cache,
            top_k=arguments.top_k,
            hybrid_candidate_k=arguments.hybrid_candidate_k,
            rrf_k=arguments.rrf_k,
        )
    if arguments.command == "rag-rerank-experiment":
        return _run_rag_rerank_experiment(
            arguments.cases,
            index_path=arguments.index_path,
            model_cache=arguments.model_cache,
            top_k=arguments.top_k,
            hybrid_candidate_k=arguments.hybrid_candidate_k,
            rrf_k=arguments.rrf_k,
            reranker_model=arguments.reranker_model,
            reranker_cache=arguments.reranker_cache,
            rerank_candidate_k=arguments.rerank_candidate_k,
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

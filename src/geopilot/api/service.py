"""Application services behind the local HTTP API."""

from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from geopilot.agent import (
    AgentMaxTurnsError,
    AgentProtocolError,
    AgentRunner,
    ModelConfigurationError,
    ModelRequestError,
    ModelResponseError,
    ModelSettings,
    build_model,
)
from geopilot.agent.models import ToolResult
from geopilot.agent.tool_adapters import build_default_tool_registry
from geopilot.api.models import (
    AgentRunRequest,
    AgentRunResponse,
    AgentToolSummary,
    ApiSettings,
    DatasetInspectRequest,
)
from geopilot.execution import (
    ApprovedPlanExecutor,
    ExecutionRun,
    PlanCompilationError,
    RunExecutionError,
    RunStore,
    RunStoreError,
)
from geopilot.memory import MemoryContextBuilder, MemoryStore, MemoryStoreError
from geopilot.models import DatasetIntakeResult
from geopilot.observability import (
    AgentTrace,
    AgentTraceStatus,
    TraceStore,
    TraceStoreError,
    build_agent_trace,
)
from geopilot.planning.models import AnalysisPlan, AnalysisPlanProposal
from geopilot.planning.store import PlanStore, PlanStoreError
from geopilot.rag import EmbeddingError, VectorStoreError, open_knowledge_retriever
from geopilot.tools.csv_point_loader import CsvPointLoadError
from geopilot.workflows.dataset_intake import inspect_and_validate_dataset


class ApiServiceError(RuntimeError):
    """Expected application failure translated into a stable HTTP response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.context = context
        super().__init__(message)


class WorkspacePlanStore(PlanStore):
    """Plan store that rejects datasets outside the API workspace."""

    def __init__(
        self,
        root: Path,
        source_resolver: Callable[[str], str | Path],
    ) -> None:
        super().__init__(root)
        self._source_resolver = source_resolver

    def create(self, proposal: AnalysisPlanProposal) -> AnalysisPlan:
        for source in proposal.datasets:
            self._source_resolver(source)
        return super().create(proposal)


class GeoPilotApiService:
    """Coordinate existing domain components without exposing CLI printing."""

    def __init__(self, settings: ApiSettings | None = None) -> None:
        self.settings = settings or ApiSettings()
        self.plan_store = WorkspacePlanStore(
            self.settings.plans_directory,
            self.resolve_workspace_source,
        )
        self.run_store = RunStore(self.settings.runs_directory)

    def resolve_workspace_source(self, source: str) -> Path:
        """Resolve user/model paths and block traversal outside the workspace."""
        candidate = Path(source)
        resolved = (
            candidate
            if candidate.is_absolute()
            else self.settings.workspace_root / candidate
        ).resolve()
        if not resolved.is_relative_to(self.settings.workspace_root):
            raise ValueError("Dataset path must remain inside the API workspace.")
        return resolved

    def inspect_dataset(self, request: DatasetInspectRequest) -> DatasetIntakeResult:
        """Inspect one authorized local dataset with existing deterministic tools."""
        try:
            return inspect_and_validate_dataset(
                self.resolve_workspace_source(request.source),
                longitude_column=request.longitude_column,
                latitude_column=request.latitude_column,
            )
        except FileNotFoundError as error:
            raise ApiServiceError(404, "dataset_not_found", str(error)) from error
        except CsvPointLoadError as error:
            raise ApiServiceError(422, error.code.value, str(error)) from error
        except ValueError as error:
            raise ApiServiceError(422, "invalid_dataset_input", str(error)) from error

    def run_agent(self, request: AgentRunRequest) -> AgentRunResponse:
        """Run the server-configured model with workspace-restricted GIS tools."""
        started = perf_counter()
        settings: ModelSettings | None = None
        try:
            settings = ModelSettings.from_environment(
                max_output_tokens=request.max_output_tokens
            )
            knowledge_retriever = (
                open_knowledge_retriever(
                    index_path=self.settings.knowledge_index,
                    cache_directory=self.settings.model_cache,
                )
                if self.settings.knowledge_index.is_file()
                else None
            )
            memory_context = (
                MemoryContextBuilder(MemoryStore(self.settings.memory_path))
                .recall(request.prompt, request.memory_namespace)
                .context
                if request.memory_enabled
                else None
            )
            runner = AgentRunner(
                build_model(settings),
                build_default_tool_registry(
                    plan_store=self.plan_store,
                    knowledge_retriever=knowledge_retriever,
                    source_resolver=self.resolve_workspace_source,
                ),
                max_model_turns=request.max_turns,
            )
            result = runner.run(request.prompt, memory_context=memory_context)
        except ModelConfigurationError as error:
            raise ApiServiceError(
                503, "model_configuration_error", str(error)
            ) from error
        except ModelRequestError as error:
            self._persist_trace(
                request.prompt,
                settings=settings,
                started=started,
                status=AgentTraceStatus.FAILED,
                error_code=error.code,
            )
            raise ApiServiceError(502, error.code, str(error)) from error
        except AgentMaxTurnsError as error:
            trace_id = self._persist_trace(
                request.prompt,
                settings=settings,
                started=started,
                status=AgentTraceStatus.FAILED,
                model_turns=error.model_turns,
                tool_results=error.tool_results,
                error_code="agent_max_turns",
            )
            raise ApiServiceError(
                504,
                "agent_max_turns",
                str(error),
                context={
                    "model_turns": error.model_turns,
                    "tools": [
                        self._tool_summary(tool).model_dump(mode="json")
                        for tool in error.tool_results
                    ],
                    "trace_id": trace_id,
                },
            ) from error
        except (AgentProtocolError, ModelResponseError) as error:
            self._persist_trace(
                request.prompt,
                settings=settings,
                started=started,
                status=AgentTraceStatus.FAILED,
                error_code="agent_runtime_error",
            )
            raise ApiServiceError(502, "agent_runtime_error", str(error)) from error
        except (EmbeddingError, VectorStoreError) as error:
            self._persist_trace(
                request.prompt,
                settings=settings,
                started=started,
                status=AgentTraceStatus.FAILED,
                error_code=error.code.value,
            )
            raise ApiServiceError(500, error.code.value, str(error)) from error
        except MemoryStoreError as error:
            self._persist_trace(
                request.prompt,
                settings=settings,
                started=started,
                status=AgentTraceStatus.FAILED,
                error_code=error.code.value,
            )
            raise ApiServiceError(500, error.code.value, str(error)) from error
        except ValueError as error:
            self._persist_trace(
                request.prompt,
                settings=settings,
                started=started,
                status=AgentTraceStatus.FAILED,
                error_code="invalid_agent_input",
            )
            raise ApiServiceError(422, "invalid_agent_input", str(error)) from error

        trace_id = self._persist_trace(
            request.prompt,
            settings=settings,
            started=started,
            status=AgentTraceStatus.SUCCEEDED,
            model_turns=result.model_turns,
            tool_results=result.tool_results,
            final_answer=result.final_answer,
        )
        return AgentRunResponse(
            answer=result.final_answer,
            model_turns=result.model_turns,
            tools=[self._tool_summary(tool) for tool in result.tool_results],
            trace_id=trace_id,
        )

    def show_plan(self, plan_id: str) -> AnalysisPlan:
        try:
            return self.plan_store.load(plan_id)
        except PlanStoreError as error:
            raise self._plan_error(error) from error

    def approve_plan(self, plan_id: str) -> AnalysisPlan:
        try:
            plan = self.plan_store.load(plan_id)
            self._validate_plan_workspace(plan)
            return self.plan_store.approve(plan_id)
        except PlanStoreError as error:
            raise self._plan_error(error) from error
        except ValueError as error:
            raise ApiServiceError(422, "unsafe_plan_dataset", str(error)) from error

    def reject_plan(self, plan_id: str, reason: str) -> AnalysisPlan:
        try:
            return self.plan_store.reject(plan_id, reason)
        except PlanStoreError as error:
            raise self._plan_error(error) from error
        except ValueError as error:
            raise ApiServiceError(
                422, "invalid_rejection_reason", str(error)
            ) from error

    def execute_plan(self, plan_id: str) -> ExecutionRun:
        try:
            plan = self.plan_store.load(plan_id)
            self._validate_plan_workspace(plan)
            return ApprovedPlanExecutor(self.plan_store, self.run_store).execute(
                plan_id,
                working_directory=self.settings.workspace_root,
            )
        except PlanStoreError as error:
            raise self._plan_error(error) from error
        except PlanCompilationError as error:
            raise ApiServiceError(409, error.code.value, str(error)) from error
        except (RunStoreError, RunExecutionError) as error:
            raise ApiServiceError(500, error.code.value, str(error)) from error
        except ValueError as error:
            raise ApiServiceError(422, "unsafe_plan_dataset", str(error)) from error

    def show_run(self, run_id: str) -> ExecutionRun:
        try:
            return self.run_store.load(run_id)
        except RunStoreError as error:
            raise self._run_store_error(error) from error

    def resume_run(self, run_id: str) -> ExecutionRun:
        try:
            run = self.run_store.load(run_id)
            self._validate_plan_workspace(self.plan_store.load(run.plan_id))
            return ApprovedPlanExecutor(self.plan_store, self.run_store).resume(run_id)
        except PlanStoreError as error:
            raise self._plan_error(error) from error
        except RunStoreError as error:
            raise self._run_store_error(error) from error
        except RunExecutionError as error:
            raise ApiServiceError(500, error.code.value, str(error)) from error
        except ValueError as error:
            raise ApiServiceError(422, "unsafe_plan_dataset", str(error)) from error

    def list_traces(
        self,
        *,
        limit: int,
        status: AgentTraceStatus | None,
    ) -> list[AgentTrace]:
        try:
            return TraceStore(self.settings.trace_path).list_traces(
                limit=limit,
                status=status,
            )
        except TraceStoreError as error:
            raise ApiServiceError(500, error.code.value, str(error)) from error
        except ValueError as error:
            raise ApiServiceError(422, "invalid_trace_query", str(error)) from error

    def _validate_plan_workspace(self, plan: AnalysisPlan) -> None:
        for source in plan.datasets:
            self.resolve_workspace_source(source)

    def _persist_trace(
        self,
        prompt: str,
        *,
        settings: ModelSettings | None,
        started: float,
        status: AgentTraceStatus,
        model_turns: int = 0,
        tool_results: Sequence[ToolResult] = (),
        final_answer: str | None = None,
        error_code: str | None = None,
    ) -> str | None:
        if settings is None:
            return None
        try:
            trace = build_agent_trace(
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
            TraceStore(self.settings.trace_path).append(trace)
        except (OSError, TraceStoreError, ValueError):
            return None
        return trace.trace_id

    @staticmethod
    def _tool_summary(result: ToolResult) -> AgentToolSummary:
        return AgentToolSummary(
            name=result.name,
            success=result.success,
            error_code=result.error_code,
        )

    @staticmethod
    def _plan_error(error: PlanStoreError) -> ApiServiceError:
        if error.code.value == "plan_not_found":
            status = 404
        elif error.code.value in {"invalid_plan_transition", "plan_not_approved"}:
            status = 409
        elif error.code.value == "invalid_plan_id":
            status = 422
        else:
            status = 500
        return ApiServiceError(status, error.code.value, str(error))

    @staticmethod
    def _run_store_error(error: RunStoreError) -> ApiServiceError:
        if error.code.value == "run_not_found":
            status = 404
        elif error.code.value == "invalid_run_id":
            status = 422
        else:
            status = 500
        return ApiServiceError(status, error.code.value, str(error))

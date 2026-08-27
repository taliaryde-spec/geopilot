"""Execute approved plans with durable checkpoints and safe resumption."""

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from geopilot.execution.compiler import compile_approved_plan
from geopilot.execution.dispatcher import dispatch_step
from geopilot.execution.models import (
    CompiledPlan,
    CompiledStep,
    ExecutionRun,
    ExecutionStatus,
    ExecutionStepRecord,
    StepDispatchResult,
)
from geopilot.execution.store import RunStore, build_running_run
from geopilot.planning.store import PlanStore

StepDispatcher = Callable[[CompiledStep, list[Path], Path], StepDispatchResult]


class RunExecutionErrorCode(StrEnum):
    """Stable identifiers for broken execution checkpoints."""

    MISSING_CHECKPOINT_ARTIFACT = "missing_checkpoint_artifact"
    MISSING_CHECKPOINT_RESULT = "missing_checkpoint_result"
    UNRESOLVED_INPUT = "unresolved_input"
    TOOL_OUTPUT_MISMATCH = "tool_output_mismatch"
    TOOL_OUTPUT_MISSING = "tool_output_missing"


class RunExecutionError(RuntimeError):
    """Raised when a stored run cannot be executed or resumed safely."""

    def __init__(
        self,
        code: RunExecutionErrorCode,
        message: str,
        *,
        step_id: int | None = None,
    ) -> None:
        self.code = code
        self.step_id = step_id
        super().__init__(message)


class ApprovedPlanExecutor:
    """Compile approved plans and dispatch deterministic GIS steps in order."""

    def __init__(
        self,
        plan_store: PlanStore,
        run_store: RunStore,
        *,
        dispatcher: StepDispatcher = dispatch_step,
    ) -> None:
        self._plan_store = plan_store
        self._run_store = run_store
        self._dispatcher = dispatcher

    def execute(
        self,
        plan_id: str,
        *,
        working_directory: str | Path | None = None,
    ) -> ExecutionRun:
        """Create and run one new attempt from an explicitly approved plan."""
        plan = self._plan_store.require_approved(plan_id)
        manifest = compile_approved_plan(plan)
        run = self._run_store.create(
            manifest,
            working_directory=working_directory or Path.cwd(),
        )
        return self._run(manifest, run)

    def resume(self, run_id: str) -> ExecutionRun:
        """Retry the first incomplete step while preserving successful artifacts."""
        run = self._run_store.load(run_id)
        self._verify_completed_checkpoints(run)
        if run.status is ExecutionStatus.SUCCEEDED:
            return run
        manifest = self._run_store.load_manifest(run_id)
        return self._run(manifest, run)

    def _run(self, manifest: CompiledPlan, run: ExecutionRun) -> ExecutionRun:
        run = build_running_run(run, now=self._run_store.now())
        artifact_sources = self._build_original_sources(manifest, run)

        for compiled_step, record in zip(manifest.steps, run.steps, strict=True):
            if record.status is ExecutionStatus.SUCCEEDED:
                artifact_sources[compiled_step.output] = Path(
                    record.artifact_path or ""
                )
                continue

            resolved_inputs = self._resolve_inputs(
                compiled_step,
                artifact_sources,
            )
            output_path = self._run_store.artifact_path(run.run_id, compiled_step)
            running_record = record.model_copy(
                update={
                    "status": ExecutionStatus.RUNNING,
                    "artifact_path": None,
                    "result_path": None,
                    "started_at": self._run_store.now(),
                    "finished_at": None,
                    "error_code": None,
                    "error_message": None,
                }
            )
            run = self._replace_step(run, running_record)
            self._run_store.save(run)

            try:
                result = self._dispatcher(
                    compiled_step,
                    resolved_inputs,
                    output_path,
                )
                actual_output = Path(result.output).resolve()
                if actual_output != output_path:
                    raise RunExecutionError(
                        RunExecutionErrorCode.TOOL_OUTPUT_MISMATCH,
                        "Tool output path does not match the allocated artifact path.",
                        step_id=compiled_step.step_id,
                    )
                if not actual_output.is_file():
                    raise RunExecutionError(
                        RunExecutionErrorCode.TOOL_OUTPUT_MISSING,
                        f"Tool reported an output that does not exist: {actual_output}",
                        step_id=compiled_step.step_id,
                    )
                result_path = self._run_store.write_step_result(
                    run.run_id,
                    compiled_step,
                    result,
                )
            # This is the process boundary: every ordinary tool/library failure
            # must become a durable failed checkpoint before control returns.
            except Exception as error:  # noqa: BLE001
                failed_at = self._run_store.now()
                failed_record = running_record.model_copy(
                    update={
                        "status": ExecutionStatus.FAILED,
                        "finished_at": failed_at,
                        "error_code": _error_code(error),
                        "error_message": str(error),
                    }
                )
                run = self._replace_step(run, failed_record).model_copy(
                    update={
                        "status": ExecutionStatus.FAILED,
                        "finished_at": failed_at,
                    }
                )
                self._run_store.save(run)
                return run

            succeeded_record = running_record.model_copy(
                update={
                    "status": ExecutionStatus.SUCCEEDED,
                    "artifact_path": str(actual_output),
                    "result_path": str(result_path),
                    "finished_at": self._run_store.now(),
                }
            )
            run = self._replace_step(run, succeeded_record)
            self._run_store.save(run)
            artifact_sources[compiled_step.output] = actual_output

        run = run.model_copy(
            update={
                "status": ExecutionStatus.SUCCEEDED,
                "finished_at": self._run_store.now(),
            }
        )
        self._run_store.save(run)
        return run

    @staticmethod
    def _build_original_sources(
        manifest: CompiledPlan,
        run: ExecutionRun,
    ) -> dict[str, Path]:
        working_directory = Path(run.working_directory)
        sources: dict[str, Path] = {}
        for dataset in manifest.datasets:
            dataset_path = Path(dataset)
            if not dataset_path.is_absolute():
                dataset_path = working_directory / dataset_path
            sources[dataset] = dataset_path.resolve()
        return sources

    @staticmethod
    def _resolve_inputs(
        step: CompiledStep,
        artifact_sources: dict[str, Path],
    ) -> list[Path]:
        unresolved = [name for name in step.inputs if name not in artifact_sources]
        if unresolved:
            raise RunExecutionError(
                RunExecutionErrorCode.UNRESOLVED_INPUT,
                "Compiled step inputs have no available artifact: "
                + ", ".join(unresolved),
                step_id=step.step_id,
            )
        return [artifact_sources[name] for name in step.inputs]

    @staticmethod
    def _replace_step(
        run: ExecutionRun,
        replacement: ExecutionStepRecord,
    ) -> ExecutionRun:
        steps = [
            replacement if step.step_id == replacement.step_id else step
            for step in run.steps
        ]
        return run.model_copy(update={"steps": steps})

    @staticmethod
    def _verify_completed_checkpoints(run: ExecutionRun) -> None:
        for step in run.steps:
            if step.status is not ExecutionStatus.SUCCEEDED:
                continue
            if step.artifact_path is None or not Path(step.artifact_path).is_file():
                raise RunExecutionError(
                    RunExecutionErrorCode.MISSING_CHECKPOINT_ARTIFACT,
                    f"Successful step artifact is missing: step {step.step_id}.",
                    step_id=step.step_id,
                )
            if step.result_path is None or not Path(step.result_path).is_file():
                raise RunExecutionError(
                    RunExecutionErrorCode.MISSING_CHECKPOINT_RESULT,
                    f"Successful step result metadata is missing: step {step.step_id}.",
                    step_id=step.step_id,
                )


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, StrEnum):
        return code.value
    if isinstance(code, str) and code:
        return code
    return "tool_execution_error"

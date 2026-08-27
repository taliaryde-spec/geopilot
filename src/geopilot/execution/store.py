"""Persist compiled manifests, run checkpoints, and tool result metadata."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from geopilot.execution.models import (
    ArtifactKind,
    CompiledPlan,
    CompiledStep,
    ExecutionRun,
    ExecutionStatus,
    ExecutionStepRecord,
    StepDispatchResult,
)


class RunStoreErrorCode(StrEnum):
    """Stable identifiers for run persistence failures."""

    INVALID_RUN_ID = "invalid_run_id"
    RUN_NOT_FOUND = "run_not_found"
    RUN_ALREADY_EXISTS = "run_already_exists"
    CORRUPT_RUN = "corrupt_run"
    RUN_MANIFEST_MISMATCH = "run_manifest_mismatch"


class RunStoreError(ValueError):
    """Raised when an execution checkpoint cannot be persisted safely."""

    def __init__(self, code: RunStoreErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


_ARTIFACT_SUFFIXES = {
    ArtifactKind.GEOPACKAGE: ".gpkg",
    ArtifactKind.GEOJSON: ".geojson",
    ArtifactKind.MARKDOWN: ".md",
}


class RunStore:
    """File-backed execution store with atomic JSON checkpoint writes."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: f"run_{uuid4().hex}")

    @property
    def root(self) -> Path:
        """Return the resolved run-storage directory."""
        return self._root

    def now(self) -> datetime:
        """Return the configured timezone-aware execution clock."""
        return self._clock()

    def create(
        self,
        manifest: CompiledPlan,
        *,
        working_directory: str | Path,
    ) -> ExecutionRun:
        """Create a new pending run and persist its immutable manifest."""
        run_id = self._id_factory()
        run_directory = self._run_directory(run_id)
        if run_directory.exists():
            raise RunStoreError(
                RunStoreErrorCode.RUN_ALREADY_EXISTS,
                f"Execution run already exists: {run_id}",
            )
        run_directory.mkdir(parents=True)
        run = ExecutionRun(
            run_id=run_id,
            plan_id=manifest.plan_id,
            working_directory=str(Path(working_directory).resolve()),
            created_at=self.now(),
            steps=[
                ExecutionStepRecord(
                    step_id=step.step_id,
                    operation=step.operation,
                    output=step.output,
                )
                for step in manifest.steps
            ],
        )
        try:
            self._write_json(
                run_directory / "manifest.json",
                manifest.model_dump_json(indent=2),
            )
            self._write_json(
                run_directory / "run.json",
                run.model_dump_json(indent=2),
            )
        except OSError:
            self._remove_empty_run_directory(run_directory)
            raise
        return run

    def load(self, run_id: str) -> ExecutionRun:
        """Load and validate one execution checkpoint."""
        path = self._run_directory(run_id) / "run.json"
        if not path.is_file():
            raise RunStoreError(
                RunStoreErrorCode.RUN_NOT_FOUND,
                f"Execution run does not exist: {run_id}",
            )
        try:
            run = ExecutionRun.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise RunStoreError(
                RunStoreErrorCode.CORRUPT_RUN,
                f"Execution run could not be read or validated: {run_id}",
            ) from error
        manifest = self.load_manifest(run_id)
        self._require_matching_manifest(run, manifest)
        return run

    def load_manifest(self, run_id: str) -> CompiledPlan:
        """Load the immutable compiled plan stored beside a run."""
        path = self._run_directory(run_id) / "manifest.json"
        if not path.is_file():
            raise RunStoreError(
                RunStoreErrorCode.CORRUPT_RUN,
                f"Execution manifest is missing: {run_id}",
            )
        try:
            return CompiledPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise RunStoreError(
                RunStoreErrorCode.CORRUPT_RUN,
                f"Execution manifest could not be read or validated: {run_id}",
            ) from error

    def save(self, run: ExecutionRun) -> None:
        """Atomically persist a validated run checkpoint."""
        checked_run = ExecutionRun.model_validate(run.model_dump())
        manifest = self.load_manifest(checked_run.run_id)
        self._require_matching_manifest(checked_run, manifest)
        self._write_json(
            self._run_directory(checked_run.run_id) / "run.json",
            checked_run.model_dump_json(indent=2),
        )

    def artifact_path(self, run_id: str, step: CompiledStep) -> Path:
        """Allocate the stable artifact path for one compiled step."""
        run_directory = self._run_directory(run_id)
        if not run_directory.is_dir():
            raise RunStoreError(
                RunStoreErrorCode.RUN_NOT_FOUND,
                f"Execution run does not exist: {run_id}",
            )
        suffix = _ARTIFACT_SUFFIXES[step.artifact_kind]
        artifacts_directory = run_directory / "artifacts"
        artifacts_directory.mkdir(exist_ok=True)
        return (
            artifacts_directory / f"{step.step_id:02d}_{step.output}{suffix}"
        ).resolve()

    def write_step_result(
        self,
        run_id: str,
        step: CompiledStep,
        result: StepDispatchResult,
    ) -> Path:
        """Persist normalized tool metadata independently from the artifact."""
        run_directory = self._run_directory(run_id)
        if not run_directory.is_dir():
            raise RunStoreError(
                RunStoreErrorCode.RUN_NOT_FOUND,
                f"Execution run does not exist: {run_id}",
            )
        results_directory = run_directory / "results"
        results_directory.mkdir(exist_ok=True)
        result_path = results_directory / f"{step.step_id:02d}_{step.output}.json"
        self._write_json(result_path, result.model_dump_json(indent=2))
        return result_path.resolve()

    def _run_directory(self, run_id: str) -> Path:
        if re.fullmatch(r"run_[A-Za-z0-9_-]+", run_id) is None:
            raise RunStoreError(
                RunStoreErrorCode.INVALID_RUN_ID,
                f"Invalid execution run identifier: {run_id!r}",
            )
        return self._root / run_id

    @staticmethod
    def _write_json(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary_path.write_text(content, encoding="utf-8")
            temporary_path.replace(path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _remove_empty_run_directory(run_directory: Path) -> None:
        if not run_directory.exists():
            return
        for child in run_directory.iterdir():
            if child.is_file():
                child.unlink()
        run_directory.rmdir()

    @staticmethod
    def _require_matching_manifest(
        run: ExecutionRun,
        manifest: CompiledPlan,
    ) -> None:
        expected_steps = [
            (step.step_id, step.operation, step.output) for step in manifest.steps
        ]
        actual_steps = [
            (step.step_id, step.operation, step.output) for step in run.steps
        ]
        if run.plan_id != manifest.plan_id or actual_steps != expected_steps:
            raise RunStoreError(
                RunStoreErrorCode.RUN_MANIFEST_MISMATCH,
                f"Run checkpoint does not match its compiled manifest: {run.run_id}",
            )


def build_running_run(run: ExecutionRun, *, now: datetime) -> ExecutionRun:
    """Return a running copy suitable for a new or resumed attempt."""
    started_at = run.started_at or now
    return run.model_copy(
        update={
            "status": ExecutionStatus.RUNNING,
            "started_at": started_at,
            "finished_at": None,
        }
    )

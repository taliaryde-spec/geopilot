"""Validated contracts for compiled plans and execution checkpoints."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from geopilot.planning.models import AnalysisOperation


class ArtifactKind(StrEnum):
    """File representation allocated for one compiled output artifact."""

    GEOPACKAGE = "geopackage"
    GEOJSON = "geojson"
    MARKDOWN = "markdown"


class ExecutionStatus(StrEnum):
    """Lifecycle shared by an execution run and its individual steps."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CompiledStep(BaseModel):
    """One plan step with resolvable artifact dependencies."""

    step_id: int = Field(ge=1)
    operation: AnalysisOperation
    inputs: list[str] = Field(min_length=1)
    output: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    artifact_kind: ArtifactKind
    parameters: dict[str, Any] = Field(default_factory=dict)


class CompiledPlan(BaseModel):
    """Machine-executable manifest derived from an approved plan."""

    plan_id: str = Field(pattern=r"^plan_[A-Za-z0-9_-]+$")
    datasets: list[str] = Field(min_length=1)
    steps: list[CompiledStep] = Field(min_length=1)


class ExecutionStepRecord(BaseModel):
    """Persistable state for one compiled operation."""

    step_id: int = Field(ge=1)
    operation: AnalysisOperation
    output: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    artifact_path: str | None = None
    result_path: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "ExecutionStepRecord":
        """Keep timestamps, artifacts, and errors consistent with status."""
        if self.status is ExecutionStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.artifact_path,
                    self.result_path,
                    self.started_at,
                    self.finished_at,
                    self.error_code,
                    self.error_message,
                )
            ):
                raise ValueError("A pending step cannot contain execution metadata.")
        elif self.status is ExecutionStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError(
                    "A running step requires started_at and no finished_at."
                )
        elif self.status is ExecutionStatus.SUCCEEDED:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.artifact_path is None
                or self.result_path is None
                or self.error_code is not None
                or self.error_message is not None
            ):
                raise ValueError(
                    "A succeeded step requires timestamps and an artifact only."
                )
        elif (
            self.started_at is None
            or self.finished_at is None
            or not self.error_code
            or not self.error_message
        ):
            raise ValueError("A failed step requires timestamps and error details.")
        return self


class ExecutionRun(BaseModel):
    """Persistable checkpoint for one approved-plan execution attempt."""

    run_id: str = Field(pattern=r"^run_[A-Za-z0-9_-]+$")
    plan_id: str = Field(pattern=r"^plan_[A-Za-z0-9_-]+$")
    working_directory: str = Field(min_length=1)
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[ExecutionStepRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "ExecutionRun":
        """Keep aggregate run state aligned with run timestamps."""
        if self.status is ExecutionStatus.PENDING:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("A pending run cannot contain execution timestamps.")
        elif self.status is ExecutionStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError(
                    "A running run requires started_at and no finished_at."
                )
        elif self.started_at is None or self.finished_at is None:
            raise ValueError("A completed run requires both execution timestamps.")

        statuses = [step.status for step in self.steps]
        if self.status is ExecutionStatus.PENDING and any(
            status is not ExecutionStatus.PENDING for status in statuses
        ):
            raise ValueError("A pending run requires every step to be pending.")
        if self.status is ExecutionStatus.SUCCEEDED and any(
            status is not ExecutionStatus.SUCCEEDED for status in statuses
        ):
            raise ValueError("A succeeded run requires every step to succeed.")
        if self.status is ExecutionStatus.FAILED:
            if ExecutionStatus.FAILED not in statuses:
                raise ValueError("A failed run requires one failed step.")
            if ExecutionStatus.RUNNING in statuses:
                raise ValueError("A failed run cannot contain a running step.")
        return self


class StepDispatchResult(BaseModel):
    """Normalized metadata returned by one deterministic GIS tool call."""

    output: str = Field(min_length=1)
    metadata: dict[str, Any]

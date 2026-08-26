"""Validated contracts for geospatial analysis plans."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AnalysisOperation(StrEnum):
    """Operations that may appear in a GeoPilot analysis plan."""

    INSPECT_DATASET = "inspect_dataset"
    RECOMMEND_METRIC_CRS = "recommend_metric_crs"
    REPROJECT = "reproject"
    BUFFER = "buffer"
    DISSOLVE = "dissolve"
    OVERLAY_INTERSECTION = "overlay_intersection"
    SPATIAL_JOIN = "spatial_join"
    CALCULATE_COVERAGE_METRICS = "calculate_coverage_metrics"
    VALIDATE_RESULT = "validate_result"
    EXPORT_GEOJSON = "export_geojson"
    GENERATE_REPORT = "generate_report"


class PlanRiskLevel(StrEnum):
    """Human-review priority for one planned operation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStatus(StrEnum):
    """Allowed states of a persisted analysis plan."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class AnalysisPlanStep(BaseModel):
    """One ordered and reviewable operation in an analysis plan."""

    step_id: int = Field(ge=1)
    operation: AnalysisOperation
    description: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = Field(min_length=1)
    risk_level: PlanRiskLevel = PlanRiskLevel.LOW


class AnalysisPlanProposal(BaseModel):
    """Model-generated plan content before application-owned metadata is added."""

    user_goal: str = Field(min_length=1)
    datasets: list[str] = Field(min_length=1)
    steps: list[AnalysisPlanStep] = Field(min_length=1)
    expected_outputs: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_order(self) -> "AnalysisPlanProposal":
        """Require simple sequential identifiers so plans are unambiguous."""
        actual_ids = [step.step_id for step in self.steps]
        expected_ids = list(range(1, len(self.steps) + 1))
        if actual_ids != expected_ids:
            raise ValueError("Plan step_id values must be sequential and start at 1.")
        return self


class AnalysisPlan(AnalysisPlanProposal):
    """Persisted plan with approval state controlled by the application."""

    plan_id: str = Field(pattern=r"^plan_[A-Za-z0-9_-]+$")
    status: PlanStatus
    created_at: datetime
    decided_at: datetime | None = None
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def validate_decision_metadata(self) -> "AnalysisPlan":
        """Keep timestamps and rejection details consistent with plan state."""
        if self.status is PlanStatus.AWAITING_APPROVAL:
            if self.decided_at is not None or self.rejection_reason is not None:
                raise ValueError("An awaiting plan cannot contain decision metadata.")
        elif self.decided_at is None:
            raise ValueError("A decided plan must contain decided_at.")

        if self.status is PlanStatus.REJECTED and not self.rejection_reason:
            raise ValueError("A rejected plan must contain a rejection reason.")
        if self.status is PlanStatus.APPROVED and self.rejection_reason is not None:
            raise ValueError("An approved plan cannot contain a rejection reason.")
        return self

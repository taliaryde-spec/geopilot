"""Adapters that expose deterministic GeoPilot workflows as Agent tools."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from geopilot.agent.registry import AgentTool, ToolRegistry
from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlanProposal,
    PlanRiskLevel,
)
from geopilot.planning.store import PlanStore
from geopilot.tools.crs_recommender import recommend_metric_crs
from geopilot.workflows.dataset_intake import inspect_and_validate_dataset


class InspectDatasetArguments(BaseModel):
    """Arguments accepted by the inspect_dataset Agent tool."""

    source: str = Field(description="Path to GeoJSON, Shapefile, or CSV")
    longitude_column: str = Field(
        default="longitude",
        description="Longitude column used for CSV input",
    )
    latitude_column: str = Field(
        default="latitude",
        description="Latitude column used for CSV input",
    )


class RecommendMetricCrsArguments(BaseModel):
    """Arguments accepted by the recommend_metric_crs Agent tool."""

    source: str = Field(description="Path to GeoJSON, Shapefile, or CSV")
    longitude_column: str = Field(
        default="longitude",
        description="Longitude column used for CSV input",
    )
    latitude_column: str = Field(
        default="latitude",
        description="Latitude column used for CSV input",
    )


class SubmitAnalysisPlanStep(BaseModel):
    """New model-submitted step with a required executable artifact id."""

    step_id: int = Field(ge=1)
    operation: AnalysisOperation
    description: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    output: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    expected_output: str = Field(min_length=1)
    risk_level: PlanRiskLevel = PlanRiskLevel.LOW


class SubmitAnalysisPlanArguments(BaseModel):
    """Executable structured plan content accepted from the language model."""

    user_goal: str = Field(min_length=1)
    datasets: list[str] = Field(min_length=1)
    steps: list[SubmitAnalysisPlanStep] = Field(min_length=1)
    expected_outputs: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_order(self) -> "SubmitAnalysisPlanArguments":
        """Require an unambiguous order before converting to stored models."""
        actual_ids = [step.step_id for step in self.steps]
        expected_ids = list(range(1, len(self.steps) + 1))
        if actual_ids != expected_ids:
            raise ValueError("Plan step_id values must be sequential and start at 1.")
        return self


def _inspect_dataset(arguments: BaseModel) -> BaseModel:
    """Validate tool arguments and run the dataset intake workflow."""
    parameters = InspectDatasetArguments.model_validate(arguments)
    return inspect_and_validate_dataset(
        parameters.source,
        longitude_column=parameters.longitude_column,
        latitude_column=parameters.latitude_column,
    )


def _recommend_metric_crs(arguments: BaseModel) -> BaseModel:
    """Validate tool arguments and determine a metric analysis CRS."""
    parameters = RecommendMetricCrsArguments.model_validate(arguments)
    return recommend_metric_crs(
        parameters.source,
        longitude_column=parameters.longitude_column,
        latitude_column=parameters.latitude_column,
    )


def _submit_analysis_plan(
    arguments: BaseModel,
    plan_store: PlanStore,
) -> BaseModel:
    """Validate model-generated plan content and persist an approval checkpoint."""
    proposal = AnalysisPlanProposal.model_validate(arguments.model_dump())
    return plan_store.create(proposal)


def build_default_tool_registry(
    *,
    plan_store: PlanStore | None = None,
) -> ToolRegistry:
    """Return the tools currently available to the GeoPilot Agent."""
    selected_plan_store = plan_store or PlanStore(Path("artifacts") / "plans")

    def submit_analysis_plan(arguments: BaseModel) -> BaseModel:
        return _submit_analysis_plan(arguments, selected_plan_store)

    registry = ToolRegistry()
    registry.register(
        AgentTool(
            name="inspect_dataset",
            description=(
                "Inspect and validate a GeoJSON, Shapefile, or coordinate CSV. "
                "Use this before making claims or planning spatial analysis."
            ),
            input_model=InspectDatasetArguments,
            handler=_inspect_dataset,
            recoverable_errors=(OSError, ValueError),
        )
    )
    registry.register(
        AgentTool(
            name="recommend_metric_crs",
            description=(
                "Deterministically recommend a metre-based projected CRS for "
                "buffer, distance, or area analysis. Use this before naming a "
                "target EPSG code or planning metric spatial operations."
            ),
            input_model=RecommendMetricCrsArguments,
            handler=_recommend_metric_crs,
            recoverable_errors=(OSError, ValueError),
        )
    )
    registry.register(
        AgentTool(
            name="submit_analysis_plan",
            description=(
                "Submit a structured GIS analysis plan for human review. Use "
                "this after inspecting inputs and resolving CRS requirements, "
                "before any reproject, buffer, spatial join, export, or report "
                "operation. Submission does not approve or execute the plan."
            ),
            input_model=SubmitAnalysisPlanArguments,
            handler=submit_analysis_plan,
            recoverable_errors=(OSError, ValueError),
        )
    )
    return registry

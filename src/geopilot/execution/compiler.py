"""Compile approved human-readable plans into resolvable manifests."""

from enum import StrEnum

from geopilot.execution.models import ArtifactKind, CompiledPlan, CompiledStep
from geopilot.planning.models import AnalysisOperation, AnalysisPlan, PlanStatus


class PlanCompilationErrorCode(StrEnum):
    """Stable identifiers for plans that cannot be executed safely."""

    PLAN_NOT_APPROVED = "plan_not_approved"
    LEGACY_PLAN_MISSING_OUTPUT = "legacy_plan_missing_output"
    DUPLICATE_DATASET = "duplicate_dataset"
    DUPLICATE_OUTPUT = "duplicate_output"
    OUTPUT_SHADOWS_DATASET = "output_shadows_dataset"
    UNKNOWN_INPUT = "unknown_input"
    UNSUPPORTED_OPERATION = "unsupported_operation"


class PlanCompilationError(ValueError):
    """Raised when a plan cannot become a deterministic execution manifest."""

    def __init__(
        self,
        code: PlanCompilationErrorCode,
        message: str,
        *,
        step_id: int | None = None,
    ) -> None:
        self.code = code
        self.step_id = step_id
        super().__init__(message)


EXECUTABLE_OPERATIONS = {
    AnalysisOperation.REPROJECT,
    AnalysisOperation.CALCULATE_GEOMETRY_AREA,
    AnalysisOperation.BUFFER,
    AnalysisOperation.DISSOLVE,
    AnalysisOperation.OVERLAY_INTERSECTION,
    AnalysisOperation.CALCULATE_COVERAGE_METRICS,
    AnalysisOperation.RESTORE_UNCOVERED_FEATURES,
    AnalysisOperation.SPATIAL_JOIN,
    AnalysisOperation.ATTRIBUTE_JOIN,
    AnalysisOperation.VALIDATE_RESULT,
    AnalysisOperation.EXPORT_GEOJSON,
    AnalysisOperation.GENERATE_REPORT,
}


def _artifact_kind(operation: AnalysisOperation) -> ArtifactKind:
    """Map an operation to the file representation its tool produces."""
    if operation is AnalysisOperation.EXPORT_GEOJSON:
        return ArtifactKind.GEOJSON
    if operation is AnalysisOperation.GENERATE_REPORT:
        return ArtifactKind.MARKDOWN
    return ArtifactKind.GEOPACKAGE


def compile_approved_plan(plan: AnalysisPlan) -> CompiledPlan:
    """Validate approval and resolve every step against prior artifacts."""
    if plan.status is not PlanStatus.APPROVED:
        raise PlanCompilationError(
            PlanCompilationErrorCode.PLAN_NOT_APPROVED,
            f"Plan is not approved: {plan.plan_id}",
        )
    if len(set(plan.datasets)) != len(plan.datasets):
        raise PlanCompilationError(
            PlanCompilationErrorCode.DUPLICATE_DATASET,
            "Plan datasets must be unique artifact sources.",
        )

    dataset_names = set(plan.datasets)
    available_artifacts = set(dataset_names)
    compiled_steps: list[CompiledStep] = []
    produced_outputs: set[str] = set()
    for step in plan.steps:
        if step.operation not in EXECUTABLE_OPERATIONS:
            raise PlanCompilationError(
                PlanCompilationErrorCode.UNSUPPORTED_OPERATION,
                f"Operation is planning-time only: {step.operation.value}",
                step_id=step.step_id,
            )
        if step.output is None:
            raise PlanCompilationError(
                PlanCompilationErrorCode.LEGACY_PLAN_MISSING_OUTPUT,
                "Plan step has no stable output artifact identifier; regenerate "
                "the plan with prompt version 0.5.0 or later.",
                step_id=step.step_id,
            )
        if step.output in dataset_names:
            raise PlanCompilationError(
                PlanCompilationErrorCode.OUTPUT_SHADOWS_DATASET,
                f"Step output shadows an input dataset: {step.output!r}.",
                step_id=step.step_id,
            )
        if step.output in produced_outputs:
            raise PlanCompilationError(
                PlanCompilationErrorCode.DUPLICATE_OUTPUT,
                f"Step output is not unique: {step.output!r}.",
                step_id=step.step_id,
            )
        unknown_inputs = [
            input_name
            for input_name in step.inputs
            if input_name not in available_artifacts
        ]
        if unknown_inputs:
            raise PlanCompilationError(
                PlanCompilationErrorCode.UNKNOWN_INPUT,
                "Step inputs do not reference original datasets or outputs from "
                "earlier steps: " + ", ".join(unknown_inputs) + ".",
                step_id=step.step_id,
            )
        compiled_steps.append(
            CompiledStep(
                step_id=step.step_id,
                operation=step.operation,
                inputs=step.inputs,
                output=step.output,
                artifact_kind=_artifact_kind(step.operation),
                parameters=step.parameters,
            )
        )
        produced_outputs.add(step.output)
        available_artifacts.add(step.output)

    return CompiledPlan(
        plan_id=plan.plan_id,
        datasets=plan.datasets,
        steps=compiled_steps,
    )

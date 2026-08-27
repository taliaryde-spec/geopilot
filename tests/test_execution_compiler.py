"""Tests for compiling approved plans into executable manifests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from geopilot.agent.tool_adapters import SubmitAnalysisPlanArguments
from geopilot.execution.compiler import (
    PlanCompilationError,
    PlanCompilationErrorCode,
    compile_approved_plan,
)
from geopilot.execution.models import (
    ArtifactKind,
    ExecutionStatus,
    ExecutionStepRecord,
)
from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlan,
    AnalysisPlanStep,
    PlanStatus,
)

FIXED_TIME = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


def build_approved_plan() -> AnalysisPlan:
    """Return a small plan with fully resolvable artifact identifiers."""
    return AnalysisPlan(
        plan_id="plan_executable123",
        status=PlanStatus.APPROVED,
        created_at=FIXED_TIME,
        decided_at=FIXED_TIME,
        user_goal="导出设施点并生成报告",
        datasets=["facilities.csv"],
        steps=[
            AnalysisPlanStep(
                step_id=1,
                operation=AnalysisOperation.REPROJECT,
                description="重投影设施点。",
                inputs=["facilities.csv"],
                parameters={"target_crs": "EPSG:32651"},
                output="facilities_projected",
                expected_output="米制设施点图层",
            ),
            AnalysisPlanStep(
                step_id=2,
                operation=AnalysisOperation.EXPORT_GEOJSON,
                description="导出 Web GeoJSON。",
                inputs=["facilities_projected"],
                parameters={"output_crs": "EPSG:4326"},
                output="facilities_web_geojson",
                expected_output="Web GeoJSON",
            ),
            AnalysisPlanStep(
                step_id=3,
                operation=AnalysisOperation.GENERATE_REPORT,
                description="生成报告。",
                inputs=["facilities_projected"],
                parameters={
                    "analysis_crs": "EPSG:32651",
                    "export_crs": "EPSG:4326",
                },
                output="facilities_report",
                expected_output="Markdown 报告",
            ),
        ],
        expected_outputs=["GeoJSON", "Markdown"],
    )


def test_compile_approved_plan_resolves_artifact_kinds() -> None:
    compiled = compile_approved_plan(build_approved_plan())

    assert compiled.plan_id == "plan_executable123"
    assert [step.output for step in compiled.steps] == [
        "facilities_projected",
        "facilities_web_geojson",
        "facilities_report",
    ]
    assert [step.artifact_kind for step in compiled.steps] == [
        ArtifactKind.GEOPACKAGE,
        ArtifactKind.GEOJSON,
        ArtifactKind.MARKDOWN,
    ]


def test_compile_rejects_legacy_plan_without_output_identifier() -> None:
    plan = build_approved_plan()
    plan.steps[0].output = None

    with pytest.raises(PlanCompilationError) as error_info:
        compile_approved_plan(plan)

    assert error_info.value.code is PlanCompilationErrorCode.LEGACY_PLAN_MISSING_OUTPUT
    assert error_info.value.step_id == 1


def test_compile_rejects_input_that_is_not_yet_available() -> None:
    plan = build_approved_plan()
    plan.steps[1].inputs = ["future_artifact"]

    with pytest.raises(PlanCompilationError) as error_info:
        compile_approved_plan(plan)

    assert error_info.value.code is PlanCompilationErrorCode.UNKNOWN_INPUT
    assert error_info.value.step_id == 2


def test_compile_rejects_duplicate_output_identifier() -> None:
    plan = build_approved_plan()
    plan.steps[1].output = "facilities_projected"

    with pytest.raises(PlanCompilationError) as error_info:
        compile_approved_plan(plan)

    assert error_info.value.code is PlanCompilationErrorCode.DUPLICATE_OUTPUT


def test_compile_rejects_unapproved_plan() -> None:
    plan_data = build_approved_plan().model_dump()
    plan_data.update(
        {
            "status": PlanStatus.AWAITING_APPROVAL,
            "decided_at": None,
        }
    )
    plan = AnalysisPlan.model_validate(plan_data)

    with pytest.raises(PlanCompilationError) as error_info:
        compile_approved_plan(plan)

    assert error_info.value.code is PlanCompilationErrorCode.PLAN_NOT_APPROVED


def test_compile_rejects_planning_time_operation() -> None:
    plan = build_approved_plan()
    plan.steps[0].operation = AnalysisOperation.INSPECT_DATASET

    with pytest.raises(PlanCompilationError) as error_info:
        compile_approved_plan(plan)

    assert error_info.value.code is PlanCompilationErrorCode.UNSUPPORTED_OPERATION


def test_step_output_identifier_requires_snake_case() -> None:
    step_data = build_approved_plan().steps[0].model_dump()
    step_data["output"] = "Facilities Projected"

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        AnalysisPlanStep.model_validate(step_data)


def test_new_model_submission_requires_output_identifier() -> None:
    plan = build_approved_plan()
    submission = {
        "user_goal": plan.user_goal,
        "datasets": plan.datasets,
        "steps": [plan.steps[0].model_dump(exclude={"output"})],
        "expected_outputs": plan.expected_outputs,
    }

    with pytest.raises(ValidationError, match="output"):
        SubmitAnalysisPlanArguments.model_validate(submission)


def test_execution_step_rejects_inconsistent_success_state() -> None:
    with pytest.raises(ValidationError, match="artifact"):
        ExecutionStepRecord(
            step_id=1,
            operation=AnalysisOperation.REPROJECT,
            output="facilities_projected",
            status=ExecutionStatus.SUCCEEDED,
            started_at=FIXED_TIME,
            finished_at=FIXED_TIME,
        )

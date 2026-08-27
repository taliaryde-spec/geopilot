"""Integration tests for durable approved-plan execution and resumption."""

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from geopilot.execution import (
    ApprovedPlanExecutor,
    ExecutionStatus,
    RunExecutionError,
    RunExecutionErrorCode,
    RunStore,
    RunStoreError,
    RunStoreErrorCode,
    StepDispatchResult,
)
from geopilot.execution.models import CompiledStep
from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlanProposal,
    AnalysisPlanStep,
)
from geopilot.planning.store import PlanStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _reprojection_step(
    step_id: int,
    *,
    source: str,
    output: str,
) -> AnalysisPlanStep:
    return AnalysisPlanStep(
        step_id=step_id,
        operation=AnalysisOperation.REPROJECT,
        description="转换为米制投影。",
        inputs=[source],
        parameters={"target_crs": "EPSG:32651"},
        output=output,
        expected_output="米制投影图层",
    )


def _approved_plan(
    plans_directory: Path,
    *,
    datasets: list[str],
    steps: list[AnalysisPlanStep],
    plan_id: str,
) -> tuple[PlanStore, str]:
    store = PlanStore(plans_directory, id_factory=lambda: plan_id)
    proposal = AnalysisPlanProposal(
        user_goal="验证批准计划执行器",
        datasets=datasets,
        steps=steps,
        expected_outputs=["投影图层"],
    )
    created = store.create(proposal)
    store.approve(created.plan_id)
    return store, created.plan_id


def test_executor_dispatches_real_reprojection_and_persists_results(
    tmp_path: Path,
) -> None:
    source = tmp_path / "facilities.geojson"
    gpd.GeoDataFrame(
        {"facility_id": [1]},
        geometry=[Point(121.47, 31.23)],
        crs="EPSG:4326",
    ).to_file(source, driver="GeoJSON")
    plan_store, plan_id = _approved_plan(
        tmp_path / "plans",
        datasets=[str(source)],
        steps=[
            _reprojection_step(
                1,
                source=str(source),
                output="facilities_projected",
            )
        ],
        plan_id="plan_real_execution",
    )
    run_store = RunStore(
        tmp_path / "runs",
        id_factory=lambda: "run_real_execution",
    )

    run = ApprovedPlanExecutor(plan_store, run_store).execute(plan_id)

    assert run.status is ExecutionStatus.SUCCEEDED
    assert run.steps[0].status is ExecutionStatus.SUCCEEDED
    assert run.steps[0].artifact_path is not None
    assert Path(run.steps[0].artifact_path).is_file()
    assert Path(run.steps[0].artifact_path).suffix == ".gpkg"
    assert run.steps[0].result_path is not None
    assert Path(run.steps[0].result_path).is_file()
    assert run_store.load(run.run_id) == run


def test_executor_resumes_at_failed_step_without_repeating_success(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.geojson"
    source.write_text("test source", encoding="utf-8")
    plan_store, plan_id = _approved_plan(
        tmp_path / "plans",
        datasets=[str(source)],
        steps=[
            _reprojection_step(1, source=str(source), output="first_output"),
            _reprojection_step(2, source="first_output", output="second_output"),
        ],
        plan_id="plan_resume_execution",
    )
    run_store = RunStore(
        tmp_path / "runs",
        id_factory=lambda: "run_resume_execution",
    )
    first_attempt_calls: list[int] = []

    def fail_second_step(
        step: CompiledStep,
        inputs: list[Path],
        output: Path,
    ) -> StepDispatchResult:
        first_attempt_calls.append(step.step_id)
        if step.step_id == 2:
            raise ValueError("simulated tool failure")
        output.write_text(inputs[0].read_text(encoding="utf-8"), encoding="utf-8")
        return StepDispatchResult(
            output=str(output),
            metadata={"step_id": step.step_id},
        )

    failed = ApprovedPlanExecutor(
        plan_store,
        run_store,
        dispatcher=fail_second_step,
    ).execute(plan_id)

    assert first_attempt_calls == [1, 2]
    assert failed.status is ExecutionStatus.FAILED
    assert failed.steps[0].status is ExecutionStatus.SUCCEEDED
    assert failed.steps[1].status is ExecutionStatus.FAILED
    assert failed.steps[1].error_code == "tool_execution_error"
    resumed_calls: list[int] = []

    def succeed_remaining_step(
        step: CompiledStep,
        inputs: list[Path],
        output: Path,
    ) -> StepDispatchResult:
        resumed_calls.append(step.step_id)
        output.write_text(inputs[0].read_text(encoding="utf-8"), encoding="utf-8")
        return StepDispatchResult(
            output=str(output),
            metadata={"step_id": step.step_id},
        )

    resumed = ApprovedPlanExecutor(
        plan_store,
        run_store,
        dispatcher=succeed_remaining_step,
    ).resume(failed.run_id)

    assert resumed_calls == [2]
    assert resumed.status is ExecutionStatus.SUCCEEDED
    assert all(step.status is ExecutionStatus.SUCCEEDED for step in resumed.steps)


def test_resume_rejects_missing_successful_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.geojson"
    source.write_text("test source", encoding="utf-8")
    plan_store, plan_id = _approved_plan(
        tmp_path / "plans",
        datasets=[str(source)],
        steps=[_reprojection_step(1, source=str(source), output="first_output")],
        plan_id="plan_missing_artifact",
    )
    run_store = RunStore(
        tmp_path / "runs",
        id_factory=lambda: "run_missing_artifact",
    )

    def write_output(
        step: CompiledStep,
        inputs: list[Path],
        output: Path,
    ) -> StepDispatchResult:
        output.write_text(inputs[0].read_text(encoding="utf-8"), encoding="utf-8")
        return StepDispatchResult(output=str(output), metadata={})

    completed = ApprovedPlanExecutor(
        plan_store,
        run_store,
        dispatcher=write_output,
    ).execute(plan_id)
    artifact_path = Path(completed.steps[0].artifact_path or "")
    artifact_path.unlink()

    with pytest.raises(RunExecutionError) as error_info:
        ApprovedPlanExecutor(plan_store, run_store).resume(completed.run_id)

    assert error_info.value.code is RunExecutionErrorCode.MISSING_CHECKPOINT_ARTIFACT


def test_run_store_rejects_path_traversal_identifier(tmp_path: Path) -> None:
    with pytest.raises(RunStoreError) as error_info:
        RunStore(tmp_path).load("../outside")

    assert error_info.value.code is RunStoreErrorCode.INVALID_RUN_ID


def test_executor_runs_complete_coverage_pipeline(tmp_path: Path) -> None:
    facilities = PROJECT_ROOT / "examples" / "data" / "facilities.csv"
    neighborhoods = PROJECT_ROOT / "examples" / "data" / "neighborhoods.geojson"
    crs = "EPSG:32651"
    common_fields = {
        "covered_area_field": "covered_area_m2",
        "coverage_ratio_field": "coverage_ratio",
        "population_field": "population",
        "estimated_covered_population_field": "estimated_covered_population",
        "facility_count_field": "facility_count",
    }
    steps = [
        _reprojection_step(
            1,
            source=str(facilities),
            output="facilities_projected",
        ),
        _reprojection_step(
            2,
            source=str(neighborhoods),
            output="neighborhoods_projected",
        ),
        AnalysisPlanStep(
            step_id=3,
            operation=AnalysisOperation.CALCULATE_GEOMETRY_AREA,
            description="计算社区总面积。",
            inputs=["neighborhoods_projected"],
            parameters={
                "output_field": "neighborhood_area_m2",
                "unit": "square_metre",
                "crs": crs,
            },
            output="neighborhoods_with_area",
            expected_output="带面积的社区图层",
        ),
        AnalysisPlanStep(
            step_id=4,
            operation=AnalysisOperation.BUFFER,
            description="按设施服务半径缓冲。",
            inputs=["facilities_projected"],
            parameters={
                "distance_field": "service_radius_m",
                "unit": "metre",
                "crs": crs,
            },
            output="facility_buffers",
            expected_output="设施缓冲区",
        ),
        AnalysisPlanStep(
            step_id=5,
            operation=AnalysisOperation.DISSOLVE,
            description="合并重叠缓冲区。",
            inputs=["facility_buffers"],
            parameters={"method": "union_all", "crs": crs},
            output="dissolved_buffers",
            expected_output="去重覆盖范围",
        ),
        AnalysisPlanStep(
            step_id=6,
            operation=AnalysisOperation.OVERLAY_INTERSECTION,
            description="社区与覆盖范围求交。",
            inputs=["neighborhoods_with_area", "dissolved_buffers"],
            parameters={"how": "intersection", "crs": crs},
            output="coverage_intersections",
            expected_output="覆盖交集",
        ),
        AnalysisPlanStep(
            step_id=7,
            operation=AnalysisOperation.CALCULATE_COVERAGE_METRICS,
            description="计算覆盖指标。",
            inputs=["coverage_intersections"],
            parameters={
                "key_field": "neighborhood_id",
                "intersection_area_field": "covered_area_m2",
                "total_area_field": "neighborhood_area_m2",
                "coverage_ratio_field": "coverage_ratio",
                "population_field": "population",
                "estimated_covered_population_field": "estimated_covered_population",
                "population_method": "area_weighted_uniform_density",
                "crs": crs,
            },
            output="coverage_metrics",
            expected_output="覆盖指标",
        ),
        AnalysisPlanStep(
            step_id=8,
            operation=AnalysisOperation.RESTORE_UNCOVERED_FEATURES,
            description="恢复零覆盖社区。",
            inputs=["neighborhoods_with_area", "coverage_metrics"],
            parameters={
                "key_field": "neighborhood_id",
                "fill_defaults": {
                    "covered_area_m2": 0,
                    "coverage_ratio": 0,
                    "estimated_covered_population": 0,
                },
                "crs": crs,
            },
            output="restored_metrics",
            expected_output="完整社区覆盖指标",
        ),
        AnalysisPlanStep(
            step_id=9,
            operation=AnalysisOperation.SPATIAL_JOIN,
            description="统计社区设施数量。",
            inputs=["neighborhoods_projected", "facilities_projected"],
            parameters={
                "key_field": "neighborhood_id",
                "output_field": "facility_count",
                "crs": crs,
                "how": "left",
                "predicate": "intersects",
                "aggregation": "count",
                "left_suffix": "neighborhood",
                "right_suffix": "facility",
            },
            output="facility_counts",
            expected_output="社区设施计数",
        ),
        AnalysisPlanStep(
            step_id=10,
            operation=AnalysisOperation.ATTRIBUTE_JOIN,
            description="连接覆盖指标与设施计数。",
            inputs=["restored_metrics", "facility_counts"],
            parameters={
                "left_key": "neighborhood_id",
                "right_key": "neighborhood_id",
                "crs": crs,
                "how": "left",
                "left_suffix": "coverage",
                "right_suffix": "count",
            },
            output="joined_result",
            expected_output="最终覆盖结果",
        ),
        AnalysisPlanStep(
            step_id=11,
            operation=AnalysisOperation.VALIDATE_RESULT,
            description="验证最终覆盖结果。",
            inputs=["joined_result"],
            parameters={
                "checks": [
                    "valid_geometry",
                    "no_null_metrics",
                    "coverage_ratio_between_0_and_1",
                    "covered_population_not_above_population",
                ],
                **common_fields,
                "crs": crs,
            },
            output="validated_result",
            expected_output="已验证结果",
        ),
        AnalysisPlanStep(
            step_id=12,
            operation=AnalysisOperation.EXPORT_GEOJSON,
            description="导出 Web GeoJSON。",
            inputs=["validated_result"],
            parameters={"output_crs": "EPSG:4326"},
            output="coverage_web",
            expected_output="Web GeoJSON",
        ),
        AnalysisPlanStep(
            step_id=13,
            operation=AnalysisOperation.GENERATE_REPORT,
            description="生成覆盖分析报告。",
            inputs=["validated_result"],
            parameters={
                "neighborhood_key_field": "neighborhood_id",
                **common_fields,
                "analysis_crs": crs,
                "export_crs": "EPSG:4326",
            },
            output="coverage_report",
            expected_output="Markdown 报告",
        ),
    ]
    plan_store, plan_id = _approved_plan(
        tmp_path / "plans",
        datasets=[str(facilities), str(neighborhoods)],
        steps=steps,
        plan_id="plan_complete_coverage",
    )
    run_store = RunStore(
        tmp_path / "runs",
        id_factory=lambda: "run_complete_coverage",
    )

    run = ApprovedPlanExecutor(plan_store, run_store).execute(plan_id)

    assert run.status is ExecutionStatus.SUCCEEDED
    assert len(run.steps) == 13
    assert all(step.status is ExecutionStatus.SUCCEEDED for step in run.steps)
    geojson_path = Path(run.steps[11].artifact_path or "")
    report_path = Path(run.steps[12].artifact_path or "")
    assert geojson_path.is_file()
    assert len(gpd.read_file(geojson_path)) == 4
    assert report_path.is_file()
    assert "GeoPilot 公共服务覆盖分析报告" in report_path.read_text(encoding="utf-8")

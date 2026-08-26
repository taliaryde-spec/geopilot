"""Tests for semantic guardrails on model-generated GIS plans."""

import pytest

from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlanProposal,
    AnalysisPlanStep,
)
from geopilot.planning.validator import (
    PlanSemanticError,
    PlanSemanticErrorCode,
    validate_analysis_plan,
)


def build_step(
    step_id: int,
    operation: AnalysisOperation,
    inputs: list[str],
    parameters: dict[str, object],
) -> AnalysisPlanStep:
    """Build one concise plan step for semantic validation tests."""
    return AnalysisPlanStep(
        step_id=step_id,
        operation=operation,
        description=f"执行 {operation.value}",
        inputs=inputs,
        parameters=parameters,
        expected_output=f"{operation.value} 输出",
    )


def build_proposal(steps: list[AnalysisPlanStep]) -> AnalysisPlanProposal:
    """Build a proposal around the supplied ordered steps."""
    return AnalysisPlanProposal(
        user_goal="计算社区公共服务覆盖率",
        datasets=["facilities.csv", "neighborhoods.geojson"],
        steps=steps,
        expected_outputs=["社区覆盖指标 GeoJSON"],
    )


def coverage_metric_parameters() -> dict[str, object]:
    """Return the explicit formula fields required for coverage metrics."""
    return {
        "intersection_area_field": "covered_area_m2",
        "total_area_field": "neighborhood_area_m2",
        "coverage_ratio_field": "coverage_ratio",
        "population_field": "population",
        "estimated_covered_population_field": "estimated_covered_population",
        "population_method": "area_weighted_uniform_density",
    }


def test_plan_rejects_ambiguous_spatial_join_parameter() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.SPATIAL_JOIN,
                ["neighborhoods", "facilities"],
                {"join_type": "intersects"},
            )
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS
    assert "separate 'how' from 'predicate'" in str(error_info.value)


def test_plan_rejects_coverage_metrics_without_dissolved_buffers() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "buffers"],
                {"how": "intersection"},
            ),
            build_step(
                3,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.INVALID_COVERAGE_SEQUENCE
    assert "buffer, dissolve, overlay_intersection" in str(error_info.value)


def test_plan_rejects_projected_geojson_output() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.EXPORT_GEOJSON,
                ["coverage_metrics"],
                {"output_crs": "EPSG:32651"},
            )
        ]
    )

    with pytest.raises(PlanSemanticError, match="EPSG:4326"):
        validate_analysis_plan(proposal)


def test_plan_rejects_multiple_inputs_for_single_dataset_tool() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.RECOMMEND_METRIC_CRS,
                ["facilities.csv", "neighborhoods.geojson"],
                {},
            )
        ]
    )

    with pytest.raises(PlanSemanticError, match="exactly 1 input"):
        validate_analysis_plan(proposal)


def test_plan_accepts_safe_area_coverage_sequence() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all"},
            ),
            build_step(
                3,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection"},
            ),
            build_step(
                4,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
            build_step(
                5,
                AnalysisOperation.VALIDATE_RESULT,
                ["coverage_metrics"],
                {
                    "checks": [
                        "valid_geometry",
                        "no_null_metrics",
                        "coverage_ratio_between_0_and_1",
                        "covered_population_not_above_population",
                    ]
                },
            ),
            build_step(
                6,
                AnalysisOperation.EXPORT_GEOJSON,
                ["validated_coverage_metrics"],
                {"output_crs": "EPSG:4326"},
            ),
        ]
    )

    assert validate_analysis_plan(proposal) is proposal

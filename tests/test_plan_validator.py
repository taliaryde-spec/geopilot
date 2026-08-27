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
        "key_field": "neighborhood_id",
        "intersection_area_field": "covered_area_m2",
        "total_area_field": "neighborhood_area_m2",
        "coverage_ratio_field": "coverage_ratio",
        "population_field": "population",
        "estimated_covered_population_field": "estimated_covered_population",
        "population_method": "area_weighted_uniform_density",
        "crs": "EPSG:32651",
    }


def uncovered_restore_parameters() -> dict[str, object]:
    """Return the zero defaults required for completely uncovered targets."""
    return {
        "key_field": "neighborhood_id",
        "crs": "EPSG:32651",
        "fill_defaults": {
            "covered_area_m2": 0,
            "coverage_ratio": 0,
            "estimated_covered_population": 0,
        },
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
                {"how": "intersection", "crs": "EPSG:32651"},
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


def test_plan_rejects_coverage_total_area_without_pre_overlay_lineage() -> None:
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
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                3,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.MISSING_AREA_LINEAGE
    assert "before overlay_intersection" in str(error_info.value)


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


def test_plan_reports_multiple_semantic_errors_in_one_response() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {},
            ),
            build_step(
                2,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                3,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                {},
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    message = str(error_info.value)
    assert "Step 1" in message
    assert "distance_field" in message
    assert "unit" in message
    assert "crs" in message
    assert "Step 4" in message
    assert "intersection_area_field" in message
    assert "total_area_field" in message
    assert "coverage_ratio_field" in message
    assert "estimated_covered_population_field" in message
    assert "population_method" in message


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


def test_plan_rejects_two_inputs_for_coverage_metrics() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersection", "neighborhoods_area"],
                coverage_metric_parameters(),
            )
        ]
    )

    with pytest.raises(PlanSemanticError, match="exactly 1 input"):
        validate_analysis_plan(proposal)


def test_plan_rejects_noncanonical_result_check_names() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.VALIDATE_RESULT,
                ["coverage_result"],
                {
                    "checks": [
                        "valid_geometry",
                        "null_metrics",
                        "coverage_ratio_in_0_1",
                        "covered_population_not_exceeding_total",
                    ]
                },
            )
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    message = str(error_info.value)
    assert "Missing required result checks" in message
    assert "Unsupported result checks" in message


def test_plan_rejects_unmerged_metrics_and_facility_counts() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.CALCULATE_GEOMETRY_AREA,
                ["projected_neighborhoods"],
                {
                    "output_field": "neighborhood_area_m2",
                    "unit": "square_metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                3,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                5,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
            build_step(
                6,
                AnalysisOperation.RESTORE_UNCOVERED_FEATURES,
                ["projected_neighborhoods", "coverage_metrics"],
                uncovered_restore_parameters(),
            ),
            build_step(
                7,
                AnalysisOperation.SPATIAL_JOIN,
                ["projected_neighborhoods", "projected_facilities"],
                {
                    "how": "left",
                    "predicate": "intersects",
                    "aggregation": "count",
                    "key_field": "neighborhood_id",
                    "output_field": "facility_count",
                    "crs": "EPSG:32651",
                    "left_suffix": "neighborhood",
                    "right_suffix": "facility",
                },
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.MISSING_RESULT_JOIN
    assert "attribute_join" in str(error_info.value)


def test_plan_rejects_missing_uncovered_feature_restore() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.CALCULATE_GEOMETRY_AREA,
                ["projected_neighborhoods"],
                {
                    "output_field": "neighborhood_area_m2",
                    "unit": "square_metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                3,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                5,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.MISSING_UNCOVERED_RESTORE
    assert "zero-coverage features are retained" in str(error_info.value)


def test_plan_rejects_incomplete_uncovered_feature_defaults() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.CALCULATE_GEOMETRY_AREA,
                ["projected_neighborhoods"],
                {
                    "output_field": "neighborhood_area_m2",
                    "unit": "square_metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                3,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                5,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
            build_step(
                6,
                AnalysisOperation.RESTORE_UNCOVERED_FEATURES,
                ["projected_neighborhoods", "coverage_metrics"],
                {
                    "key_field": "neighborhood_id",
                    "crs": "EPSG:32651",
                    "fill_defaults": {
                        "covered_area_m2": 0,
                        "estimated_covered_population": 0,
                    },
                },
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.MISSING_UNCOVERED_RESTORE
    assert "coverage_ratio" in str(error_info.value)


def test_plan_rejects_restore_without_complete_target_polygons() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.CALCULATE_GEOMETRY_AREA,
                ["projected_neighborhoods"],
                {
                    "output_field": "neighborhood_area_m2",
                    "unit": "square_metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                3,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                5,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
            build_step(
                6,
                AnalysisOperation.RESTORE_UNCOVERED_FEATURES,
                ["coverage_intersections", "coverage_metrics"],
                uncovered_restore_parameters(),
            ),
        ]
    )

    with pytest.raises(PlanSemanticError) as error_info:
        validate_analysis_plan(proposal)

    assert error_info.value.code is PlanSemanticErrorCode.MISSING_UNCOVERED_RESTORE
    assert "complete target polygon" in str(error_info.value)


def test_plan_accepts_safe_area_coverage_sequence() -> None:
    proposal = build_proposal(
        [
            build_step(
                1,
                AnalysisOperation.CALCULATE_GEOMETRY_AREA,
                ["projected_neighborhoods"],
                {
                    "output_field": "neighborhood_area_m2",
                    "unit": "square_metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                2,
                AnalysisOperation.BUFFER,
                ["projected_facilities"],
                {
                    "distance_field": "service_radius_m",
                    "unit": "metre",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                3,
                AnalysisOperation.DISSOLVE,
                ["facility_buffers"],
                {"method": "union_all", "crs": "EPSG:32651"},
            ),
            build_step(
                4,
                AnalysisOperation.OVERLAY_INTERSECTION,
                ["projected_neighborhoods", "dissolved_buffers"],
                {"how": "intersection", "crs": "EPSG:32651"},
            ),
            build_step(
                5,
                AnalysisOperation.CALCULATE_COVERAGE_METRICS,
                ["coverage_intersections"],
                coverage_metric_parameters(),
            ),
            build_step(
                6,
                AnalysisOperation.RESTORE_UNCOVERED_FEATURES,
                ["projected_neighborhoods", "coverage_metrics"],
                uncovered_restore_parameters(),
            ),
            build_step(
                7,
                AnalysisOperation.SPATIAL_JOIN,
                ["projected_neighborhoods", "projected_facilities"],
                {
                    "how": "left",
                    "predicate": "intersects",
                    "aggregation": "count",
                    "key_field": "neighborhood_id",
                    "output_field": "facility_count",
                    "crs": "EPSG:32651",
                    "left_suffix": "neighborhood",
                    "right_suffix": "facility",
                },
            ),
            build_step(
                8,
                AnalysisOperation.ATTRIBUTE_JOIN,
                ["restored_coverage_metrics", "facility_counts"],
                {
                    "how": "left",
                    "left_key": "neighborhood_id",
                    "right_key": "neighborhood_id",
                    "crs": "EPSG:32651",
                    "left_suffix": "coverage",
                    "right_suffix": "facility_count",
                },
            ),
            build_step(
                9,
                AnalysisOperation.VALIDATE_RESULT,
                ["combined_coverage_result"],
                {
                    "checks": [
                        "valid_geometry",
                        "no_null_metrics",
                        "coverage_ratio_between_0_and_1",
                        "covered_population_not_above_population",
                    ],
                    "covered_area_field": "covered_area_m2",
                    "coverage_ratio_field": "coverage_ratio",
                    "population_field": "population",
                    "estimated_covered_population_field": "estimated_covered_population",
                    "facility_count_field": "facility_count",
                    "crs": "EPSG:32651",
                },
            ),
            build_step(
                10,
                AnalysisOperation.EXPORT_GEOJSON,
                ["validated_coverage_metrics"],
                {"output_crs": "EPSG:4326"},
            ),
        ]
    )

    assert validate_analysis_plan(proposal) is proposal

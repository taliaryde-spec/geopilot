"""Tests for validated GeoJSON and Markdown analysis outputs."""

from pathlib import Path

import geopandas as gpd
import pytest

from geopilot.tools.coverage_analysis import (
    calculate_coverage_metrics,
    count_spatial_relationships,
    join_coverage_attributes,
    restore_uncovered_features,
)
from geopilot.tools.result_outputs import (
    REQUIRED_RESULT_CHECKS,
    ResultOutputError,
    ResultOutputErrorCode,
    export_web_geojson,
    generate_coverage_report,
    validate_coverage_result,
)
from geopilot.tools.vector_operations import (
    buffer_by_distance_field,
    calculate_polygon_area,
    dissolve_coverage_buffers,
    intersect_polygon_datasets,
    reproject_vector_dataset,
)

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[1] / "examples" / "data"


def build_joined_coverage_result(tmp_path: Path) -> Path:
    """Execute deterministic plan steps 1 through 10 in a test directory."""
    facilities = tmp_path / "facilities_32651.gpkg"
    neighborhoods = tmp_path / "neighborhoods_32651.gpkg"
    neighborhoods_with_area = tmp_path / "neighborhoods_with_area.gpkg"
    buffers = tmp_path / "facility_buffers.gpkg"
    dissolved = tmp_path / "service_coverage.gpkg"
    intersections = tmp_path / "coverage_intersections.gpkg"
    metrics = tmp_path / "coverage_metrics.gpkg"
    restored = tmp_path / "restored_coverage.gpkg"
    counts = tmp_path / "facility_counts.gpkg"
    joined = tmp_path / "joined_result.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        facilities,
        target_crs="EPSG:32651",
    )
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "neighborhoods.geojson",
        neighborhoods,
        target_crs="EPSG:32651",
    )
    calculate_polygon_area(
        neighborhoods,
        neighborhoods_with_area,
        output_field="neighborhood_area_m2",
        crs="EPSG:32651",
    )
    buffer_by_distance_field(
        facilities,
        buffers,
        distance_field="service_radius_m",
        crs="EPSG:32651",
    )
    dissolve_coverage_buffers(buffers, dissolved, crs="EPSG:32651")
    intersect_polygon_datasets(
        neighborhoods_with_area,
        dissolved,
        intersections,
        crs="EPSG:32651",
    )
    calculate_coverage_metrics(
        intersections,
        metrics,
        key_field="neighborhood_id",
        intersection_area_field="covered_area_m2",
        total_area_field="neighborhood_area_m2",
        coverage_ratio_field="coverage_ratio",
        population_field="population",
        estimated_covered_population_field="estimated_covered_population",
        population_method="area_weighted_uniform_density",
        crs="EPSG:32651",
    )
    restore_uncovered_features(
        neighborhoods_with_area,
        metrics,
        restored,
        key_field="neighborhood_id",
        fill_defaults={
            "covered_area_m2": 0,
            "coverage_ratio": 0,
            "estimated_covered_population": 0,
        },
        crs="EPSG:32651",
    )
    count_spatial_relationships(
        neighborhoods,
        facilities,
        counts,
        key_field="neighborhood_id",
        output_field="facility_count",
        crs="EPSG:32651",
        left_suffix="_nbh",
        right_suffix="_fac",
    )
    join_coverage_attributes(
        restored,
        counts,
        joined,
        left_key="neighborhood_id",
        right_key="neighborhood_id",
        crs="EPSG:32651",
        left_suffix="_cov",
        right_suffix="_cnt",
    )
    return joined


def validate_sample_result(source: Path, output: Path) -> None:
    """Apply the exact four checks required by the approved plan."""
    validate_coverage_result(
        source,
        output,
        checks=sorted(REQUIRED_RESULT_CHECKS),
        covered_area_field="covered_area_m2",
        coverage_ratio_field="coverage_ratio",
        population_field="population",
        estimated_covered_population_field="estimated_covered_population",
        facility_count_field="facility_count",
        crs="EPSG:32651",
    )


def test_validate_coverage_result_persists_passing_checkpoint(
    tmp_path: Path,
) -> None:
    joined = build_joined_coverage_result(tmp_path)
    validated = tmp_path / "validated_result.gpkg"

    result = validate_coverage_result(
        joined,
        validated,
        checks=sorted(REQUIRED_RESULT_CHECKS),
        covered_area_field="covered_area_m2",
        coverage_ratio_field="coverage_ratio",
        population_field="population",
        estimated_covered_population_field="estimated_covered_population",
        facility_count_field="facility_count",
        crs="EPSG:32651",
    )

    persisted = gpd.read_file(validated)
    assert result.passed is True
    assert all(result.checks.values())
    assert result.feature_count == 4
    assert len(persisted) == 4


def test_validate_coverage_result_rejects_ratio_above_one(tmp_path: Path) -> None:
    joined = build_joined_coverage_result(tmp_path)
    invalid = tmp_path / "invalid_result.gpkg"
    invalid_frame = gpd.read_file(joined)
    invalid_frame.loc[0, "coverage_ratio"] = 1.1
    invalid_frame.to_file(invalid, layer="data", driver="GPKG", index=False)

    with pytest.raises(ResultOutputError) as error_info:
        validate_sample_result(invalid, tmp_path / "should_not_exist.gpkg")

    assert error_info.value.code is ResultOutputErrorCode.VALIDATION_FAILED
    assert "coverage_ratio_between_0_and_1" in error_info.value.failed_checks
    assert not (tmp_path / "should_not_exist.gpkg").exists()


def test_export_web_geojson_reprojects_validated_result(tmp_path: Path) -> None:
    joined = build_joined_coverage_result(tmp_path)
    validated = tmp_path / "validated_result.gpkg"
    geojson = tmp_path / "coverage_result.geojson"
    validate_sample_result(joined, validated)

    result = export_web_geojson(validated, geojson, output_crs="EPSG:4326")

    persisted = gpd.read_file(geojson)
    assert result.feature_count == 4
    assert result.source_crs == "EPSG:32651"
    assert result.output_crs == "EPSG:4326"
    assert persisted.crs is not None
    assert persisted.crs.to_epsg() == 4326
    assert "coverage_ratio" in persisted.columns
    assert result.bounds is not None
    assert 121 < result.bounds[0] < 122
    assert 31 < result.bounds[1] < 32


def test_export_web_geojson_rejects_non_wgs84_output(tmp_path: Path) -> None:
    joined = build_joined_coverage_result(tmp_path)

    with pytest.raises(ResultOutputError) as error_info:
        export_web_geojson(
            joined,
            tmp_path / "coverage.geojson",
            output_crs="EPSG:3857",
        )

    assert error_info.value.code is ResultOutputErrorCode.INVALID_OUTPUT_CRS


def test_generate_coverage_report_is_grounded_in_result_rows(
    tmp_path: Path,
) -> None:
    joined = build_joined_coverage_result(tmp_path)
    validated = tmp_path / "validated_result.gpkg"
    report_path = tmp_path / "coverage_report.md"
    validate_sample_result(joined, validated)

    result = generate_coverage_report(
        validated,
        report_path,
        neighborhood_key_field="neighborhood_id",
        population_field="population",
        covered_area_field="covered_area_m2",
        coverage_ratio_field="coverage_ratio",
        estimated_covered_population_field="estimated_covered_population",
        facility_count_field="facility_count",
        analysis_crs="EPSG:32651",
        export_crs="EPSG:4326",
    )

    report = report_path.read_text(encoding="utf-8")
    assert result.neighborhood_count == 4
    assert result.zero_coverage_count >= 1
    assert result.total_population == 42_500
    assert 0 <= result.population_coverage_ratio <= 1
    assert result.facility_relationship_count == 4
    assert "EPSG:32651" in report
    assert "EPSG:4326" in report
    assert "社区内部人口均匀分布" in report
    assert "社区—设施空间匹配数量：4" in report

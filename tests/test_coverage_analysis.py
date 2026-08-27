"""Tests for deterministic coverage metrics and result joins."""

from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
import pytest

from geopilot.tools.coverage_analysis import (
    CoverageOperationError,
    CoverageOperationErrorCode,
    calculate_coverage_metrics,
    count_spatial_relationships,
    join_coverage_attributes,
    restore_uncovered_features,
)
from geopilot.tools.vector_operations import (
    buffer_by_distance_field,
    calculate_polygon_area,
    dissolve_coverage_buffers,
    intersect_polygon_datasets,
    reproject_vector_dataset,
)

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[1] / "examples" / "data"


def build_intersection_inputs(tmp_path: Path) -> dict[str, Path]:
    """Build the approved plan's deterministic geometry artifacts."""
    paths = {
        "facilities": tmp_path / "facilities_32651.gpkg",
        "neighborhoods": tmp_path / "neighborhoods_32651.gpkg",
        "neighborhoods_with_area": tmp_path / "neighborhoods_with_area.gpkg",
        "buffers": tmp_path / "facility_buffers.gpkg",
        "dissolved": tmp_path / "service_coverage.gpkg",
        "intersections": tmp_path / "coverage_intersections.gpkg",
    }
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        paths["facilities"],
        target_crs="EPSG:32651",
    )
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "neighborhoods.geojson",
        paths["neighborhoods"],
        target_crs="EPSG:32651",
    )
    calculate_polygon_area(
        paths["neighborhoods"],
        paths["neighborhoods_with_area"],
        output_field="neighborhood_area_m2",
        crs="EPSG:32651",
    )
    buffer_by_distance_field(
        paths["facilities"],
        paths["buffers"],
        distance_field="service_radius_m",
        crs="EPSG:32651",
    )
    dissolve_coverage_buffers(
        paths["buffers"],
        paths["dissolved"],
        crs="EPSG:32651",
    )
    intersect_polygon_datasets(
        paths["neighborhoods_with_area"],
        paths["dissolved"],
        paths["intersections"],
        crs="EPSG:32651",
    )
    return paths


def run_coverage_metrics(source: Path, output: Path) -> None:
    """Calculate the metric fields used by the approved sample plan."""
    calculate_coverage_metrics(
        source,
        output,
        key_field="neighborhood_id",
        intersection_area_field="covered_area_m2",
        total_area_field="neighborhood_area_m2",
        coverage_ratio_field="coverage_ratio",
        population_field="population",
        estimated_covered_population_field="estimated_covered_population",
        population_method="area_weighted_uniform_density",
        crs="EPSG:32651",
    )


def test_calculate_coverage_metrics_uses_explicit_formulas(tmp_path: Path) -> None:
    paths = build_intersection_inputs(tmp_path)
    metrics_path = tmp_path / "coverage_metrics.gpkg"

    run_coverage_metrics(paths["intersections"], metrics_path)

    metrics = gpd.read_file(metrics_path)
    geometry = cast(gpd.GeoSeries, metrics.geometry)
    covered_area = cast(pd.Series, metrics["covered_area_m2"]).astype(float)
    total_area = cast(pd.Series, metrics["neighborhood_area_m2"]).astype(float)
    coverage_ratio = cast(pd.Series, metrics["coverage_ratio"]).astype(float)
    population = cast(pd.Series, metrics["population"]).astype(float)
    covered_population = cast(
        pd.Series,
        metrics["estimated_covered_population"],
    ).astype(float)
    assert metrics["neighborhood_id"].is_unique
    assert covered_area.to_numpy() == pytest.approx(geometry.area.to_numpy())
    assert coverage_ratio.to_numpy() == pytest.approx(
        (covered_area / total_area).to_numpy()
    )
    assert covered_population.to_numpy() == pytest.approx(
        (population * coverage_ratio).to_numpy()
    )
    assert ((coverage_ratio >= 0) & (coverage_ratio <= 1)).all()


def test_calculate_coverage_metrics_rejects_non_positive_total_area(
    tmp_path: Path,
) -> None:
    paths = build_intersection_inputs(tmp_path)
    invalid_source = tmp_path / "invalid_intersections.gpkg"
    intersections = gpd.read_file(paths["intersections"])
    intersections.loc[0, "neighborhood_area_m2"] = 0
    intersections.to_file(
        invalid_source,
        layer="data",
        driver="GPKG",
        index=False,
    )

    with pytest.raises(CoverageOperationError) as error_info:
        run_coverage_metrics(invalid_source, tmp_path / "metrics.gpkg")

    assert error_info.value.code is CoverageOperationErrorCode.NON_POSITIVE_TOTAL_AREA


def test_restore_uncovered_features_keeps_every_neighborhood(
    tmp_path: Path,
) -> None:
    paths = build_intersection_inputs(tmp_path)
    metrics_path = tmp_path / "coverage_metrics.gpkg"
    restored_path = tmp_path / "restored_metrics.gpkg"
    run_coverage_metrics(paths["intersections"], metrics_path)

    result = restore_uncovered_features(
        paths["neighborhoods_with_area"],
        metrics_path,
        restored_path,
        key_field="neighborhood_id",
        fill_defaults={
            "covered_area_m2": 0,
            "coverage_ratio": 0,
            "estimated_covered_population": 0,
        },
        crs="EPSG:32651",
    )

    restored = gpd.read_file(restored_path)
    geometry = cast(gpd.GeoSeries, restored.geometry)
    target_area = cast(pd.Series, restored["neighborhood_area_m2"]).astype(float)
    ratios = cast(pd.Series, restored["coverage_ratio"]).astype(float)
    assert result.feature_count == 4
    assert result.restored_feature_count >= 1
    assert restored["neighborhood_id"].is_unique
    restored_metric_fields = restored[
        ["covered_area_m2", "coverage_ratio", "estimated_covered_population"]
    ]
    assert int(restored_metric_fields.isna().to_numpy().sum()) == 0
    assert geometry.area.to_numpy() == pytest.approx(target_area.to_numpy())
    assert int((ratios == 0).sum()) == result.restored_feature_count


def test_restore_all_targets_when_intersection_is_empty(tmp_path: Path) -> None:
    paths = build_intersection_inputs(tmp_path)
    empty_intersections = tmp_path / "empty_intersections.gpkg"
    empty_metrics = tmp_path / "empty_metrics.gpkg"
    restored_path = tmp_path / "restored_metrics.gpkg"
    intersections = gpd.read_file(paths["intersections"])
    intersections.iloc[0:0].to_file(
        empty_intersections,
        layer="data",
        driver="GPKG",
        index=False,
    )
    run_coverage_metrics(empty_intersections, empty_metrics)

    result = restore_uncovered_features(
        paths["neighborhoods_with_area"],
        empty_metrics,
        restored_path,
        key_field="neighborhood_id",
        fill_defaults={
            "covered_area_m2": 0,
            "coverage_ratio": 0,
            "estimated_covered_population": 0,
        },
        crs="EPSG:32651",
    )

    restored = gpd.read_file(restored_path)
    assert result.feature_count == 4
    assert result.restored_feature_count == 4
    assert (restored["covered_area_m2"] == 0).all()
    assert (restored["coverage_ratio"] == 0).all()
    assert (restored["estimated_covered_population"] == 0).all()


def test_count_spatial_relationships_includes_zero_counts(tmp_path: Path) -> None:
    paths = build_intersection_inputs(tmp_path)
    counts_path = tmp_path / "facility_counts.gpkg"

    result = count_spatial_relationships(
        paths["neighborhoods"],
        paths["facilities"],
        counts_path,
        key_field="neighborhood_id",
        output_field="facility_count",
        crs="EPSG:32651",
        how="left",
        predicate="intersects",
        aggregation="count",
        left_suffix="_nbh",
        right_suffix="_fac",
    )

    counts = gpd.read_file(counts_path).set_index("neighborhood_id")
    assert result.feature_count == 4
    assert result.relationship_count == 4
    assert counts["facility_count"].to_dict() == {
        "N001": 2,
        "N002": 1,
        "N003": 1,
        "N004": 0,
    }


def test_join_coverage_attributes_preserves_canonical_left_fields(
    tmp_path: Path,
) -> None:
    paths = build_intersection_inputs(tmp_path)
    metrics_path = tmp_path / "coverage_metrics.gpkg"
    restored_path = tmp_path / "restored_metrics.gpkg"
    counts_path = tmp_path / "facility_counts.gpkg"
    joined_path = tmp_path / "joined_result.gpkg"
    run_coverage_metrics(paths["intersections"], metrics_path)
    restore_uncovered_features(
        paths["neighborhoods_with_area"],
        metrics_path,
        restored_path,
        key_field="neighborhood_id",
        fill_defaults={
            "covered_area_m2": 0,
            "coverage_ratio": 0,
            "estimated_covered_population": 0,
        },
        crs="EPSG:32651",
    )
    count_spatial_relationships(
        paths["neighborhoods"],
        paths["facilities"],
        counts_path,
        key_field="neighborhood_id",
        output_field="facility_count",
        crs="EPSG:32651",
        left_suffix="_nbh",
        right_suffix="_fac",
    )

    result = join_coverage_attributes(
        restored_path,
        counts_path,
        joined_path,
        left_key="neighborhood_id",
        right_key="neighborhood_id",
        crs="EPSG:32651",
        how="left",
        left_suffix="_cov",
        right_suffix="_cnt",
    )

    joined = gpd.read_file(joined_path)
    assert result.feature_count == 4
    assert result.matched_feature_count == 4
    assert result.unmatched_feature_count == 0
    assert "population" in joined.columns
    assert "facility_count" in joined.columns
    assert "population_cov" not in joined.columns
    joined_metric_fields = joined[
        [
            "covered_area_m2",
            "coverage_ratio",
            "estimated_covered_population",
            "facility_count",
        ]
    ]
    assert int(joined_metric_fields.isna().to_numpy().sum()) == 0

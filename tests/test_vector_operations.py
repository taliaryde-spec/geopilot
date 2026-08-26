"""Tests for deterministic, file-backed vector operations."""

from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from geopilot.tools.vector_operations import (
    VectorOperationError,
    VectorOperationErrorCode,
    buffer_by_distance_field,
    calculate_polygon_area,
    dissolve_coverage_buffers,
    intersect_polygon_datasets,
    reproject_vector_dataset,
)

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[1] / "examples" / "data"


def test_reproject_coordinate_csv_to_metric_geopackage(tmp_path: Path) -> None:
    output = tmp_path / "facilities_32651.gpkg"

    result = reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        output,
        target_crs="EPSG:32651",
    )

    persisted = gpd.read_file(output)
    assert result.output == str(output.resolve())
    assert result.feature_count == 5
    assert result.geometry_types == {"Point": 5}
    assert result.source_crs == "EPSG:4326"
    assert result.target_crs == "EPSG:32651"
    assert persisted.crs is not None
    assert persisted.crs.to_epsg() == 32651
    assert len(persisted) == 5


def test_reproject_rejects_geographic_target_crs(tmp_path: Path) -> None:
    with pytest.raises(VectorOperationError) as error_info:
        reproject_vector_dataset(
            SAMPLE_DATA_DIR / "facilities.csv",
            tmp_path / "facilities.gpkg",
            target_crs="EPSG:4326",
        )

    assert error_info.value.code is VectorOperationErrorCode.CRS_NOT_PROJECTED


def test_reproject_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "facilities.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        output,
        target_crs="EPSG:32651",
    )

    with pytest.raises(VectorOperationError) as error_info:
        reproject_vector_dataset(
            SAMPLE_DATA_DIR / "facilities.csv",
            output,
            target_crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.OUTPUT_EXISTS


def test_reproject_requires_geopackage_output(tmp_path: Path) -> None:
    with pytest.raises(VectorOperationError) as error_info:
        reproject_vector_dataset(
            SAMPLE_DATA_DIR / "facilities.csv",
            tmp_path / "facilities.geojson",
            target_crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.UNSUPPORTED_OUTPUT_FORMAT


def test_calculate_polygon_area_in_square_metres(tmp_path: Path) -> None:
    projected = tmp_path / "neighborhoods_32651.gpkg"
    output = tmp_path / "neighborhoods_with_area.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "neighborhoods.geojson",
        projected,
        target_crs="EPSG:32651",
    )

    result = calculate_polygon_area(
        projected,
        output,
        output_field="neighborhood_area_m2",
        crs="EPSG:32651",
    )

    persisted = gpd.read_file(output)
    persisted_areas = cast(
        pd.Series,
        persisted["neighborhood_area_m2"],
    ).astype(float)
    assert result.feature_count == 4
    assert result.geometry_types == {"Polygon": 4}
    assert result.crs == "EPSG:32651"
    assert result.minimum_area_m2 > 0
    assert result.maximum_area_m2 >= result.minimum_area_m2
    assert result.total_area_m2 == pytest.approx(
        float(persisted_areas.to_numpy().sum())
    )
    assert (persisted_areas > 0).all()


def test_calculate_polygon_area_rejects_geographic_crs(tmp_path: Path) -> None:
    with pytest.raises(VectorOperationError) as error_info:
        calculate_polygon_area(
            SAMPLE_DATA_DIR / "neighborhoods.geojson",
            tmp_path / "areas.gpkg",
            output_field="area_m2",
            crs="EPSG:4326",
        )

    assert error_info.value.code is VectorOperationErrorCode.CRS_NOT_PROJECTED


def test_calculate_polygon_area_rejects_point_geometry(tmp_path: Path) -> None:
    projected = tmp_path / "facilities_32651.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        projected,
        target_crs="EPSG:32651",
    )

    with pytest.raises(VectorOperationError) as error_info:
        calculate_polygon_area(
            projected,
            tmp_path / "facility_areas.gpkg",
            output_field="area_m2",
            crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.NON_POLYGON_GEOMETRY


def test_vector_operation_rejects_missing_crs(tmp_path: Path) -> None:
    source = tmp_path / "missing_crs.shp"
    frame = gpd.GeoDataFrame(
        {"name": ["Unknown"]},
        geometry=[Point(121.47, 31.23)],
    )
    with pytest.warns(UserWarning, match="crs"):
        frame.to_file(source)

    with pytest.raises(VectorOperationError) as error_info:
        reproject_vector_dataset(
            source,
            tmp_path / "projected.gpkg",
            target_crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.MISSING_CRS


def test_buffer_by_positive_metre_distance_field(tmp_path: Path) -> None:
    projected = tmp_path / "facilities_32651.gpkg"
    buffered = tmp_path / "facility_buffers.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        projected,
        target_crs="EPSG:32651",
    )

    result = buffer_by_distance_field(
        projected,
        buffered,
        distance_field="service_radius_m",
        crs="EPSG:32651",
    )

    persisted = gpd.read_file(buffered)
    geometry = cast(gpd.GeoSeries, persisted.geometry)
    assert result.feature_count == 5
    assert result.geometry_types == {"Polygon": 5}
    assert result.minimum_distance_m == 1000
    assert result.maximum_distance_m == 1000
    assert result.quadrant_segments == 16
    assert persisted.crs is not None
    assert persisted.crs.to_epsg() == 32651
    assert (geometry.area > 0).all()


def test_buffer_rejects_missing_distance_field(tmp_path: Path) -> None:
    projected = tmp_path / "facilities_32651.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        projected,
        target_crs="EPSG:32651",
    )

    with pytest.raises(VectorOperationError) as error_info:
        buffer_by_distance_field(
            projected,
            tmp_path / "buffers.gpkg",
            distance_field="missing_radius",
            crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.MISSING_FIELD


def test_buffer_rejects_non_positive_distance(tmp_path: Path) -> None:
    projected = tmp_path / "facilities_32651.gpkg"
    invalid_source = tmp_path / "invalid_distances.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        projected,
        target_crs="EPSG:32651",
    )
    frame = gpd.read_file(projected)
    frame.loc[0, "service_radius_m"] = 0
    frame.to_file(invalid_source, layer="data", driver="GPKG", index=False)

    with pytest.raises(VectorOperationError) as error_info:
        buffer_by_distance_field(
            invalid_source,
            tmp_path / "buffers.gpkg",
            distance_field="service_radius_m",
            crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.NON_POSITIVE_DISTANCE


def test_buffer_rejects_non_numeric_distance(tmp_path: Path) -> None:
    projected = tmp_path / "facilities_32651.gpkg"
    invalid_source = tmp_path / "invalid_distances.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        projected,
        target_crs="EPSG:32651",
    )
    frame = gpd.read_file(projected)
    frame["service_radius_m"] = frame["service_radius_m"].astype(str)
    frame.loc[0, "service_radius_m"] = "unknown"
    frame.to_file(invalid_source, layer="data", driver="GPKG", index=False)

    with pytest.raises(VectorOperationError) as error_info:
        buffer_by_distance_field(
            invalid_source,
            tmp_path / "buffers.gpkg",
            distance_field="service_radius_m",
            crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.INVALID_DISTANCE_VALUES


def test_dissolve_removes_overlapping_buffer_area(tmp_path: Path) -> None:
    projected = tmp_path / "facilities_32651.gpkg"
    buffered = tmp_path / "facility_buffers.gpkg"
    dissolved = tmp_path / "service_coverage.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "facilities.csv",
        projected,
        target_crs="EPSG:32651",
    )
    buffer_by_distance_field(
        projected,
        buffered,
        distance_field="service_radius_m",
        crs="EPSG:32651",
    )

    result = dissolve_coverage_buffers(
        buffered,
        dissolved,
        crs="EPSG:32651",
    )

    input_geometry = cast(gpd.GeoSeries, gpd.read_file(buffered).geometry)
    output_geometry = cast(gpd.GeoSeries, gpd.read_file(dissolved).geometry)
    assert result.input_feature_count == 5
    assert result.feature_count == 1
    assert result.method == "union_all"
    assert result.geometry_types in ({"Polygon": 1}, {"MultiPolygon": 1})
    assert float(output_geometry.area.sum()) < float(input_geometry.area.sum())


def test_dissolve_rejects_unsafe_method(tmp_path: Path) -> None:
    with pytest.raises(VectorOperationError) as error_info:
        dissolve_coverage_buffers(
            SAMPLE_DATA_DIR / "neighborhoods.geojson",
            tmp_path / "dissolved.gpkg",
            crs="EPSG:32651",
            method="by_attribute",
        )

    assert error_info.value.code is VectorOperationErrorCode.UNSUPPORTED_METHOD


def test_intersect_preserves_neighborhood_fields_and_clips_coverage(
    tmp_path: Path,
) -> None:
    facilities = tmp_path / "facilities_32651.gpkg"
    neighborhoods = tmp_path / "neighborhoods_32651.gpkg"
    neighborhoods_with_area = tmp_path / "neighborhoods_with_area.gpkg"
    buffers = tmp_path / "facility_buffers.gpkg"
    dissolved = tmp_path / "service_coverage.gpkg"
    intersections = tmp_path / "coverage_intersections.gpkg"
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

    result = intersect_polygon_datasets(
        neighborhoods_with_area,
        dissolved,
        intersections,
        crs="EPSG:32651",
    )

    persisted = gpd.read_file(intersections)
    intersection_geometry = cast(gpd.GeoSeries, persisted.geometry)
    neighborhood_areas = cast(
        pd.Series,
        persisted["neighborhood_area_m2"],
    ).astype(float)
    assert result.left_feature_count == 4
    assert result.right_feature_count == 1
    assert result.feature_count > 0
    assert result.how == "intersection"
    assert "neighborhood_id" in persisted.columns
    assert "population" in persisted.columns
    assert "neighborhood_area_m2" in persisted.columns
    assert (intersection_geometry.area <= neighborhood_areas).all()


def test_intersect_rejects_crs_mismatch(tmp_path: Path) -> None:
    left = tmp_path / "neighborhoods_32651.gpkg"
    right = tmp_path / "neighborhoods_32650.gpkg"
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "neighborhoods.geojson",
        left,
        target_crs="EPSG:32651",
    )
    reproject_vector_dataset(
        SAMPLE_DATA_DIR / "neighborhoods.geojson",
        right,
        target_crs="EPSG:32650",
    )

    with pytest.raises(VectorOperationError) as error_info:
        intersect_polygon_datasets(
            left,
            right,
            tmp_path / "intersection.gpkg",
            crs="EPSG:32651",
        )

    assert error_info.value.code is VectorOperationErrorCode.CRS_MISMATCH


def test_intersect_persists_empty_result_for_no_coverage(tmp_path: Path) -> None:
    left_source = tmp_path / "left.gpkg"
    right_source = tmp_path / "right.gpkg"
    output = tmp_path / "empty_intersection.gpkg"
    gpd.GeoDataFrame(
        {"neighborhood_id": ["N001"]},
        geometry=[box(0, 0, 10, 10)],
        crs="EPSG:32651",
    ).to_file(left_source, layer="data", driver="GPKG", index=False)
    gpd.GeoDataFrame(
        geometry=[box(100, 100, 110, 110)],
        crs="EPSG:32651",
    ).to_file(right_source, layer="data", driver="GPKG", index=False)

    result = intersect_polygon_datasets(
        left_source,
        right_source,
        output,
        crs="EPSG:32651",
    )

    persisted = gpd.read_file(output)
    assert result.feature_count == 0
    assert result.geometry_types == {}
    assert persisted.empty
    assert "neighborhood_id" in persisted.columns

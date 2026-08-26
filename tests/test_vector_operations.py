"""Tests for deterministic, file-backed vector operations."""

from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from geopilot.tools.vector_operations import (
    VectorOperationError,
    VectorOperationErrorCode,
    calculate_polygon_area,
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

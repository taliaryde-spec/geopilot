"""Tests for converting longitude and latitude CSV columns to points."""

from pathlib import Path

import pandas as pd
import pytest

from geopilot.models import ValidationIssueCode
from geopilot.tools.csv_point_loader import (
    CsvPointErrorCode,
    CsvPointLoadError,
    load_csv_points,
)
from geopilot.workflows.dataset_intake import inspect_and_validate_dataset


def write_csv(path: Path, data: dict[str, list[object]]) -> None:
    """Write a small CSV fixture without including a DataFrame index."""
    pd.DataFrame(data).to_csv(path, index=False)


def test_load_csv_points_creates_epsg_4326_geometries(tmp_path: Path) -> None:
    dataset_path = tmp_path / "facilities.csv"
    write_csv(
        dataset_path,
        {
            "name": ["Clinic A", "Clinic B"],
            "longitude": [121.47, 121.48],
            "latitude": [31.23, 31.24],
        },
    )

    frame = load_csv_points(dataset_path)

    assert frame.crs is not None
    assert frame.crs.to_string() == "EPSG:4326"
    assert frame.geometry.geom_type.tolist() == ["Point", "Point"]
    assert frame.geometry.x.tolist() == pytest.approx([121.47, 121.48])
    assert frame.geometry.y.tolist() == pytest.approx([31.23, 31.24])


def test_load_csv_points_supports_custom_coordinate_columns(tmp_path: Path) -> None:
    dataset_path = tmp_path / "custom_columns.csv"
    write_csv(
        dataset_path,
        {
            "name": ["Clinic A"],
            "lon": [121.47],
            "lat": [31.23],
        },
    )

    frame = load_csv_points(
        dataset_path,
        longitude_column="lon",
        latitude_column="lat",
    )

    assert frame.geometry.x.iloc[0] == pytest.approx(121.47)
    assert frame.geometry.y.iloc[0] == pytest.approx(31.23)


def test_load_csv_points_accepts_coordinate_range_endpoints(tmp_path: Path) -> None:
    dataset_path = tmp_path / "range_endpoints.csv"
    write_csv(
        dataset_path,
        {
            "longitude": [-180.0, 180.0],
            "latitude": [-90.0, 90.0],
        },
    )

    frame = load_csv_points(dataset_path)

    assert frame.geometry.x.tolist() == pytest.approx([-180.0, 180.0])
    assert frame.geometry.y.tolist() == pytest.approx([-90.0, 90.0])


def test_load_csv_points_reports_empty_file(tmp_path: Path) -> None:
    dataset_path = tmp_path / "empty.csv"
    dataset_path.touch()

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is CsvPointErrorCode.CSV_READ_ERROR


def test_load_csv_points_rejects_missing_coordinate_columns(tmp_path: Path) -> None:
    dataset_path = tmp_path / "missing_columns.csv"
    write_csv(dataset_path, {"name": ["Clinic A"]})

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is CsvPointErrorCode.MISSING_COORDINATE_COLUMNS


def test_load_csv_points_rejects_same_coordinate_column(tmp_path: Path) -> None:
    dataset_path = tmp_path / "same_column.csv"
    write_csv(dataset_path, {"coordinate": [121.47]})

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(
            dataset_path,
            longitude_column="coordinate",
            latitude_column="coordinate",
        )

    assert error_info.value.code is CsvPointErrorCode.COORDINATE_COLUMNS_NOT_DISTINCT


def test_load_csv_points_rejects_missing_coordinates(tmp_path: Path) -> None:
    dataset_path = tmp_path / "missing_coordinates.csv"
    write_csv(
        dataset_path,
        {
            "longitude": [121.47, None],
            "latitude": [31.23, 31.24],
        },
    )

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is CsvPointErrorCode.MISSING_COORDINATES
    assert error_info.value.count == 1
    assert error_info.value.row_numbers == [3]


def test_load_csv_points_treats_whitespace_as_missing(tmp_path: Path) -> None:
    dataset_path = tmp_path / "whitespace.csv"
    write_csv(
        dataset_path,
        {
            "longitude": ["   "],
            "latitude": [31.23],
        },
    )

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is CsvPointErrorCode.MISSING_COORDINATES
    assert error_info.value.row_numbers == [2]


def test_load_csv_points_rejects_non_numeric_coordinates(tmp_path: Path) -> None:
    dataset_path = tmp_path / "non_numeric.csv"
    write_csv(
        dataset_path,
        {
            "longitude": ["not-a-number"],
            "latitude": [31.23],
        },
    )

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is CsvPointErrorCode.NON_NUMERIC_COORDINATES


def test_load_csv_points_rejects_existing_geometry_column(tmp_path: Path) -> None:
    dataset_path = tmp_path / "geometry_conflict.csv"
    write_csv(
        dataset_path,
        {
            "longitude": [121.47],
            "latitude": [31.23],
            "geometry": ["POINT (121.47 31.23)"],
        },
    )

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is CsvPointErrorCode.GEOMETRY_COLUMN_CONFLICT


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected_code"),
    [
        (180.01, 31.23, CsvPointErrorCode.LONGITUDE_OUT_OF_RANGE),
        (121.47, -90.01, CsvPointErrorCode.LATITUDE_OUT_OF_RANGE),
    ],
)
def test_load_csv_points_rejects_out_of_range_coordinates(
    tmp_path: Path,
    longitude: float,
    latitude: float,
    expected_code: CsvPointErrorCode,
) -> None:
    dataset_path = tmp_path / "out_of_range.csv"
    write_csv(
        dataset_path,
        {
            "longitude": [longitude],
            "latitude": [latitude],
        },
    )

    with pytest.raises(CsvPointLoadError) as error_info:
        load_csv_points(dataset_path)

    assert error_info.value.code is expected_code


def test_header_only_csv_is_rejected_by_dataset_validation(tmp_path: Path) -> None:
    dataset_path = tmp_path / "header_only.CSV"
    write_csv(dataset_path, {"longitude": [], "latitude": []})

    result = inspect_and_validate_dataset(dataset_path)

    assert result.profile.feature_count == 0
    assert result.validation.can_proceed is False
    assert result.validation.issues[0].code is ValidationIssueCode.EMPTY_DATASET

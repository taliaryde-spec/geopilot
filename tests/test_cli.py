"""Integration tests for the GeoPilot command-line interface."""

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from geopilot.cli import (
    EXIT_FILE_NOT_FOUND,
    EXIT_SUCCESS,
    EXIT_VALIDATION_ERROR,
    main,
)


def test_main_without_command_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == EXIT_SUCCESS
    assert "inspect" in captured.out


def test_main_inspects_valid_dataset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "facilities.geojson"
    frame = gpd.GeoDataFrame(
        {"name": ["Clinic A"]},
        geometry=[Point(121.47, 31.23)],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert payload["profile"]["feature_count"] == 1
    assert payload["profile"]["crs"] == "EPSG:4326"
    assert payload["validation"]["can_proceed"] is True


def test_main_allows_dataset_with_validation_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "facilities_with_missing_name.geojson"
    frame = gpd.GeoDataFrame(
        {"name": ["Clinic A", None]},
        geometry=[Point(121.47, 31.23), Point(121.48, 31.24)],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert payload["validation"]["can_proceed"] is True
    assert payload["validation"]["issues"][0]["severity"] == "warning"


def test_main_reports_missing_dataset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "missing.geojson"

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_FILE_NOT_FOUND
    assert captured.out == ""
    assert payload["error"]["code"] == "dataset_not_found"


def test_main_returns_validation_error_for_invalid_geometry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "invalid.geojson"
    invalid_polygon = Polygon(
        [
            (0, 0),
            (1, 1),
            (1, 0),
            (0, 1),
            (0, 0),
        ]
    )
    frame = gpd.GeoDataFrame(
        {"name": ["Invalid area"]},
        geometry=[invalid_polygon],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_VALIDATION_ERROR
    assert payload["validation"]["can_proceed"] is False
    assert payload["validation"]["issues"][0]["code"] == "invalid_geometry"

"""Integration tests for the GeoPilot command-line interface."""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

import geopilot.cli as cli_module
from geopilot.agent.models import ModelResponse
from geopilot.cli import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_FILE_NOT_FOUND,
    EXIT_INPUT_ERROR,
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
    assert "agent" in captured.out


def test_main_reports_missing_model_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEOPILOT_PROVIDER", raising=False)
    monkeypatch.delenv("GEOPILOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEOPILOT_MODEL", raising=False)

    exit_code = main(["agent", "检查示例数据"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "model_configuration_error"


def test_main_runs_agent_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeModel:
        def complete(self, messages: object, tools: object) -> ModelResponse:
            return ModelResponse(content="Agent 已返回测试答案。")

    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    monkeypatch.setattr(cli_module, "build_model", lambda settings: FakeModel())

    exit_code = main(["agent", "检查示例数据"])
    captured = capsys.readouterr()

    assert exit_code == EXIT_SUCCESS
    assert captured.out == "Agent 已返回测试答案。\n"
    assert captured.err == ""


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


def test_main_inspects_csv_with_custom_coordinate_columns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "facilities.csv"
    pd.DataFrame(
        {
            "name": ["Clinic A"],
            "lon": [121.47],
            "lat": [31.23],
        }
    ).to_csv(dataset_path, index=False)

    exit_code = main(
        [
            "inspect",
            str(dataset_path),
            "--longitude-column",
            "lon",
            "--latitude-column",
            "lat",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert payload["profile"]["geometry_types"] == {"Point": 1}
    assert payload["profile"]["crs"] == "EPSG:4326"
    assert payload["validation"]["can_proceed"] is True


def test_main_reports_csv_coordinate_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "invalid_coordinates.csv"
    pd.DataFrame(
        {
            "longitude": [181.0],
            "latitude": [31.23],
        }
    ).to_csv(dataset_path, index=False)

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_INPUT_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "longitude_out_of_range"


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

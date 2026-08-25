"""Regression tests for the tracked GeoPilot demonstration datasets."""

from pathlib import Path

import pytest

from geopilot.workflows.dataset_intake import inspect_and_validate_dataset

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[1] / "examples" / "data"


@pytest.mark.parametrize(
    ("filename", "feature_count", "geometry_types"),
    [
        ("facilities.geojson", 5, {"Point": 5}),
        ("facilities.csv", 5, {"Point": 5}),
        ("neighborhoods.geojson", 4, {"Polygon": 4}),
    ],
)
def test_sample_dataset_is_analysis_ready(
    filename: str,
    feature_count: int,
    geometry_types: dict[str, int],
) -> None:
    result = inspect_and_validate_dataset(SAMPLE_DATA_DIR / filename)

    assert result.profile.feature_count == feature_count
    assert result.profile.geometry_types == geometry_types
    assert result.profile.crs == "EPSG:4326"
    assert all(count == 0 for count in result.profile.missing_values.values())
    assert result.profile.invalid_geometry_count == 0
    assert result.profile.empty_geometry_count == 0
    assert result.validation.can_proceed is True
    assert result.validation.issues == []

"""Tests for vector dataset inspection."""

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, Point, Polygon

from geopilot.tools.dataset_inspector import inspect_vector_dataset


def test_inspect_vector_dataset(tmp_path: Path) -> None:
    dataset_path = tmp_path / "facilities.geojson"

    frame = gpd.GeoDataFrame(
        {
            "name": ["Clinic A", None],
            "capacity": [20, 40],
        },
        geometry=[
            Point(121.47, 31.23),
            Point(121.48, 31.24),
        ],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    profile = inspect_vector_dataset(dataset_path)

    assert profile.source == str(dataset_path.resolve())
    assert profile.feature_count == 2
    assert profile.columns == ["name", "capacity", "geometry"]
    assert profile.geometry_column == "geometry"
    assert profile.geometry_types == {"Point": 2}
    assert profile.crs == "EPSG:4326"
    assert profile.bounds is not None
    assert profile.bounds == pytest.approx((121.47, 31.23, 121.48, 31.24))
    assert profile.missing_values == {
        "name": 1,
        "capacity": 0,
        "geometry": 0,
    }
    assert profile.invalid_geometry_count == 0
    assert profile.empty_geometry_count == 0


def test_inspect_vector_dataset_rejects_missing_file(tmp_path: Path) -> None:
    dataset_path = tmp_path / "missing.geojson"

    with pytest.raises(FileNotFoundError, match="Dataset does not exist"):
        inspect_vector_dataset(dataset_path)


def test_inspect_vector_dataset_does_not_guess_missing_crs(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "no_crs.shp"
    frame = gpd.GeoDataFrame(
        {"name": ["Unknown location"]},
        geometry=[Point(121.47, 31.23)],
    )

    with pytest.warns(UserWarning, match="crs"):
        frame.to_file(dataset_path)

    profile = inspect_vector_dataset(dataset_path)

    assert profile.crs is None


def test_inspect_vector_dataset_counts_problem_geometries(tmp_path: Path) -> None:
    dataset_path = tmp_path / "problem_geometries.geojson"
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
        {"name": ["Empty", "Invalid", "Missing"]},
        geometry=[GeometryCollection(), invalid_polygon, Point()],
        crs="EPSG:4326",
    )
    frame.at[2, "geometry"] = None
    frame.to_file(dataset_path, driver="GeoJSON")

    profile = inspect_vector_dataset(dataset_path)

    assert profile.feature_count == 3
    assert profile.geometry_types == {
        "GeometryCollection": 1,
        "Polygon": 1,
    }
    assert profile.missing_values["geometry"] == 1
    assert profile.invalid_geometry_count == 1
    assert profile.empty_geometry_count == 1
    assert profile.bounds is not None
    assert profile.bounds == pytest.approx((0.0, 0.0, 1.0, 1.0))

"""Tests for deterministic metric CRS recommendations."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from geopilot.models import MetricCrsRecommendationMethod
from geopilot.tools.crs_recommender import (
    CrsRecommendationError,
    CrsRecommendationErrorCode,
    recommend_metric_crs,
)

SAMPLE_DATASET = (
    Path(__file__).resolve().parents[1] / "examples" / "data" / "facilities.csv"
)


def test_recommend_metric_crs_selects_shanghai_utm_zone() -> None:
    recommendation = recommend_metric_crs(SAMPLE_DATASET)

    assert recommendation.source == str(SAMPLE_DATASET.resolve())
    assert recommendation.source_crs == "EPSG:4326"
    assert recommendation.recommended_crs == "EPSG:32651"
    assert recommendation.recommended_epsg == 32651
    assert recommendation.linear_unit == "metre"
    assert recommendation.requires_reprojection is True
    assert recommendation.method is MetricCrsRecommendationMethod.ESTIMATED_UTM_CRS
    assert recommendation.warnings == []


def test_recommend_metric_crs_keeps_existing_metre_projection(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "projected.gpkg"
    frame = gpd.GeoDataFrame(
        {"name": ["Clinic A"]},
        geometry=[Point(355_000, 3_456_000)],
        crs="EPSG:32651",
    )
    frame.to_file(dataset_path, driver="GPKG")

    recommendation = recommend_metric_crs(dataset_path)

    assert recommendation.recommended_epsg == 32651
    assert recommendation.requires_reprojection is False
    assert recommendation.method is MetricCrsRecommendationMethod.EXISTING_METRIC_CRS


def test_recommend_metric_crs_rejects_missing_crs(tmp_path: Path) -> None:
    dataset_path = tmp_path / "missing_crs.shp"
    frame = gpd.GeoDataFrame(
        {"name": ["Unknown location"]},
        geometry=[Point(121.47, 31.23)],
    )
    with pytest.warns(UserWarning, match="crs"):
        frame.to_file(dataset_path)

    with pytest.raises(CrsRecommendationError) as error_info:
        recommend_metric_crs(dataset_path)

    assert error_info.value.code is CrsRecommendationErrorCode.MISSING_CRS


def test_recommend_metric_crs_warns_for_wide_extent(tmp_path: Path) -> None:
    dataset_path = tmp_path / "wide.csv"
    pd.DataFrame(
        {
            "longitude": [100.0, 110.0],
            "latitude": [31.0, 31.0],
        }
    ).to_csv(dataset_path, index=False)

    recommendation = recommend_metric_crs(dataset_path)

    assert recommendation.recommended_epsg is not None
    assert len(recommendation.warnings) == 1
    assert "more than 6 degrees" in recommendation.warnings[0]

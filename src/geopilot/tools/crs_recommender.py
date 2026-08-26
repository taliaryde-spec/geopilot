"""Recommend a projected CRS for deterministic metric spatial analysis."""

from enum import StrEnum
from pathlib import Path
from typing import cast

import geopandas as gpd

from geopilot.models import (
    MetricCrsRecommendation,
    MetricCrsRecommendationMethod,
)
from geopilot.tools.dataset_loader import load_geospatial_dataset


class CrsRecommendationErrorCode(StrEnum):
    """Stable identifiers for failures to recommend a metric CRS."""

    MISSING_CRS = "missing_crs"
    MISSING_GEOMETRY = "missing_geometry"
    ESTIMATION_FAILED = "crs_estimation_failed"


class CrsRecommendationError(ValueError):
    """Raised when a safe metric CRS cannot be determined."""

    def __init__(self, code: CrsRecommendationErrorCode, message: str) -> None:
        """Store a stable error code alongside the explanation."""
        self.code = code
        super().__init__(message)


def _non_empty_geometry(frame: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Return geometries that can contribute to a CRS estimate."""
    geometry = frame.geometry
    non_null = cast(gpd.GeoSeries, geometry[~geometry.isna()])
    return cast(gpd.GeoSeries, non_null[~non_null.is_empty])


def _uses_metres(frame: gpd.GeoDataFrame) -> bool:
    """Return whether the declared projected CRS uses metres on every axis."""
    crs = frame.crs
    if crs is None or not crs.is_projected or not crs.axis_info:
        return False
    return all(
        abs(float(axis.unit_conversion_factor) - 1.0) < 1e-12 for axis in crs.axis_info
    )


def _linear_unit(frame: gpd.GeoDataFrame) -> str:
    """Return the first declared CRS axis unit."""
    crs = frame.crs
    if crs is None or not crs.axis_info:
        return "unknown"
    return str(crs.axis_info[0].unit_name)


def _extent_warnings(frame: gpd.GeoDataFrame) -> list[str]:
    """Warn when a single UTM zone may not represent the full dataset well."""
    crs = frame.crs
    if crs is None:
        return []

    geographic_frame = frame if crs.is_geographic else frame.to_crs("EPSG:4326")
    geometry = _non_empty_geometry(geographic_frame)
    min_x, _, max_x, _ = geometry.total_bounds
    longitude_span = float(max_x - min_x)
    if longitude_span > 6.0:
        return [
            (
                "Dataset spans more than 6 degrees of longitude; verify that one "
                "UTM zone provides acceptable distortion for the planned analysis."
            )
        ]
    return []


def recommend_metric_crs(
    source: str | Path,
    *,
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
) -> MetricCrsRecommendation:
    """Recommend a metre-based projected CRS using declared data and extent."""
    source_path = Path(source).resolve()
    frame = load_geospatial_dataset(
        source_path,
        longitude_column=longitude_column,
        latitude_column=latitude_column,
    )

    if frame.crs is None:
        raise CrsRecommendationError(
            CrsRecommendationErrorCode.MISSING_CRS,
            "Dataset has no declared CRS; assign the correct source CRS before "
            "requesting a metric projection.",
        )
    if _non_empty_geometry(frame).empty:
        raise CrsRecommendationError(
            CrsRecommendationErrorCode.MISSING_GEOMETRY,
            "Dataset has no non-empty geometry from which to estimate a CRS.",
        )

    source_crs = frame.crs.to_string()
    source_epsg = frame.crs.to_epsg()
    if _uses_metres(frame) and source_epsg != 3857:
        return MetricCrsRecommendation(
            source=str(source_path),
            source_crs=source_crs,
            recommended_crs=source_crs,
            recommended_epsg=source_epsg,
            linear_unit=_linear_unit(frame),
            requires_reprojection=False,
            method=MetricCrsRecommendationMethod.EXISTING_METRIC_CRS,
        )

    warnings = _extent_warnings(frame)
    if source_epsg == 3857:
        warnings.append(
            "Web Mercator can significantly distort distance and area; a local "
            "UTM CRS is recommended instead."
        )

    try:
        recommended = frame.estimate_utm_crs()
    except (RuntimeError, ValueError) as error:
        raise CrsRecommendationError(
            CrsRecommendationErrorCode.ESTIMATION_FAILED,
            f"A local UTM CRS could not be estimated: {error}",
        ) from error
    if recommended is None:
        raise CrsRecommendationError(
            CrsRecommendationErrorCode.ESTIMATION_FAILED,
            "A local UTM CRS could not be estimated from the dataset extent.",
        )

    recommended_crs = recommended.to_string()
    linear_unit = (
        str(recommended.axis_info[0].unit_name) if recommended.axis_info else "unknown"
    )
    return MetricCrsRecommendation(
        source=str(source_path),
        source_crs=source_crs,
        recommended_crs=recommended_crs,
        recommended_epsg=recommended.to_epsg(),
        linear_unit=linear_unit,
        requires_reprojection=frame.crs != recommended,
        method=MetricCrsRecommendationMethod.ESTIMATED_UTM_CRS,
        warnings=warnings,
    )

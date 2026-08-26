"""Deterministic vector transformations used only after plan approval."""

from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import cast
from uuid import uuid4

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from pyproj.exceptions import CRSError

from geopilot.models import (
    BufferResult,
    DissolveResult,
    GeometryAreaResult,
    OverlayIntersectionResult,
    ReprojectionResult,
)
from geopilot.tools.dataset_loader import load_geospatial_dataset


class VectorOperationErrorCode(StrEnum):
    """Stable identifiers for unsafe or invalid vector operations."""

    EMPTY_DATASET = "empty_dataset"
    MISSING_CRS = "missing_crs"
    MISSING_GEOMETRY = "missing_geometry"
    INVALID_GEOMETRY = "invalid_geometry"
    INVALID_TARGET_CRS = "invalid_target_crs"
    CRS_NOT_PROJECTED = "crs_not_projected"
    CRS_NOT_METRIC = "crs_not_metric"
    CRS_MISMATCH = "crs_mismatch"
    NON_POLYGON_GEOMETRY = "non_polygon_geometry"
    MISSING_FIELD = "missing_field"
    INVALID_DISTANCE_VALUES = "invalid_distance_values"
    NON_POSITIVE_DISTANCE = "non_positive_distance"
    INVALID_BUFFER_RESOLUTION = "invalid_buffer_resolution"
    UNSUPPORTED_METHOD = "unsupported_method"
    UNSUPPORTED_OVERLAY = "unsupported_overlay"
    INVALID_FIELD_NAME = "invalid_field_name"
    FIELD_ALREADY_EXISTS = "field_already_exists"
    UNSUPPORTED_OUTPUT_FORMAT = "unsupported_output_format"
    OUTPUT_EXISTS = "output_exists"


class VectorOperationError(ValueError):
    """Raised when a deterministic vector operation is unsafe to run."""

    def __init__(self, code: VectorOperationErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _geometry_type_counts(frame: gpd.GeoDataFrame) -> dict[str, int]:
    """Return stable geometry-type counts for result metadata."""
    geometry = cast(gpd.GeoSeries, frame.geometry)
    counts = geometry.geom_type.value_counts()
    return {str(name): int(count) for name, count in counts.items()}


def _load_valid_dataset(
    source: str | Path,
    *,
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
) -> tuple[Path, gpd.GeoDataFrame]:
    """Load data and reject conditions that make transformations unsafe."""
    source_path = Path(source).resolve()
    frame = load_geospatial_dataset(
        source_path,
        longitude_column=longitude_column,
        latitude_column=latitude_column,
    )
    if frame.empty:
        raise VectorOperationError(
            VectorOperationErrorCode.EMPTY_DATASET,
            f"Dataset contains no features: {source_path}",
        )
    if frame.crs is None:
        raise VectorOperationError(
            VectorOperationErrorCode.MISSING_CRS,
            "Dataset has no declared CRS; GeoPilot will not guess one before "
            "a spatial transformation.",
        )

    geometry = cast(gpd.GeoSeries, frame.geometry)
    missing_count = int(geometry.isna().sum()) + int(geometry.is_empty.sum())
    if missing_count:
        raise VectorOperationError(
            VectorOperationErrorCode.MISSING_GEOMETRY,
            f"Dataset contains {missing_count} null or empty geometries.",
        )
    invalid_count = int((~geometry.is_valid).sum())
    if invalid_count:
        raise VectorOperationError(
            VectorOperationErrorCode.INVALID_GEOMETRY,
            f"Dataset contains {invalid_count} invalid geometries.",
        )
    return source_path, frame


def _parse_crs(value: str, *, label: str) -> CRS:
    """Parse user-supplied CRS text into a validated CRS object."""
    try:
        return CRS.from_user_input(value)
    except CRSError as error:
        raise VectorOperationError(
            VectorOperationErrorCode.INVALID_TARGET_CRS,
            f"{label} is not a valid CRS: {value!r}.",
        ) from error


def _require_metric_projected_crs(crs: CRS) -> None:
    """Require a projected CRS whose axes use metres."""
    if not crs.is_projected:
        raise VectorOperationError(
            VectorOperationErrorCode.CRS_NOT_PROJECTED,
            f"CRS must be projected for metric analysis: {crs.to_string()}.",
        )
    if not crs.axis_info or not all(
        abs(float(axis.unit_conversion_factor) - 1.0) < 1e-12 for axis in crs.axis_info
    ):
        raise VectorOperationError(
            VectorOperationErrorCode.CRS_NOT_METRIC,
            f"CRS axes must use metres: {crs.to_string()}.",
        )


def _require_matching_crs(
    frame: gpd.GeoDataFrame,
    expected_crs: CRS,
    *,
    dataset_label: str = "Dataset",
) -> CRS:
    """Return the actual CRS only when it matches the declared analysis CRS."""
    actual_crs = cast(CRS, frame.crs)
    if actual_crs != expected_crs:
        raise VectorOperationError(
            VectorOperationErrorCode.CRS_MISMATCH,
            f"{dataset_label} CRS does not match the explicitly requested "
            f"analysis CRS: {actual_crs.to_string()} != "
            f"{expected_crs.to_string()}.",
        )
    return actual_crs


def _require_polygon_geometry(
    frame: gpd.GeoDataFrame,
    *,
    operation: str,
) -> None:
    """Reject non-area geometries before polygon-only operations."""
    geometry_types = set(_geometry_type_counts(frame))
    unsupported_types = geometry_types - {"Polygon", "MultiPolygon"}
    if unsupported_types:
        raise VectorOperationError(
            VectorOperationErrorCode.NON_POLYGON_GEOMETRY,
            f"{operation} only accepts Polygon or MultiPolygon geometry; "
            f"received: {', '.join(sorted(unsupported_types))}.",
        )


def _prepare_output(output: str | Path, *, overwrite: bool) -> Path:
    """Resolve a GeoPackage output and prevent accidental replacement."""
    output_path = Path(output).resolve()
    if output_path.suffix.lower() != ".gpkg":
        raise VectorOperationError(
            VectorOperationErrorCode.UNSUPPORTED_OUTPUT_FORMAT,
            "Intermediate vector outputs must use the .gpkg extension.",
        )
    if output_path.exists() and not overwrite:
        raise VectorOperationError(
            VectorOperationErrorCode.OUTPUT_EXISTS,
            f"Output already exists and overwrite is disabled: {output_path}",
        )
    return output_path


def _write_geopackage(
    frame: gpd.GeoDataFrame,
    output: str | Path,
    *,
    overwrite: bool,
) -> Path:
    """Write a single-layer GeoPackage using an atomic final replacement."""
    output_path = _prepare_output(output, overwrite=overwrite)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.stem}-{uuid4().hex}.tmp.gpkg"
    )
    try:
        frame.to_file(
            temporary_path,
            layer="data",
            driver="GPKG",
            index=False,
        )
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return output_path


def reproject_vector_dataset(
    source: str | Path,
    output: str | Path,
    *,
    target_crs: str,
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
    overwrite: bool = False,
) -> ReprojectionResult:
    """Reproject one validated vector dataset into a metre-based CRS."""
    source_path, frame = _load_valid_dataset(
        source,
        longitude_column=longitude_column,
        latitude_column=latitude_column,
    )
    target = _parse_crs(target_crs, label="target_crs")
    _require_metric_projected_crs(target)
    source_crs = cast(CRS, frame.crs)
    reprojected = frame.to_crs(target)
    output_path = _write_geopackage(
        reprojected,
        output,
        overwrite=overwrite,
    )
    return ReprojectionResult(
        source=str(source_path),
        output=str(output_path),
        feature_count=len(reprojected),
        geometry_types=_geometry_type_counts(reprojected),
        source_crs=source_crs.to_string(),
        target_crs=target.to_string(),
    )


def calculate_polygon_area(
    source: str | Path,
    output: str | Path,
    *,
    output_field: str,
    crs: str,
    overwrite: bool = False,
) -> GeometryAreaResult:
    """Persist polygon areas in square metres under an explicit field name."""
    source_path, frame = _load_valid_dataset(source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(frame, expected_crs)

    cleaned_field = output_field.strip()
    if not cleaned_field:
        raise VectorOperationError(
            VectorOperationErrorCode.INVALID_FIELD_NAME,
            "Area output_field must not be empty.",
        )
    if cleaned_field in frame.columns:
        raise VectorOperationError(
            VectorOperationErrorCode.FIELD_ALREADY_EXISTS,
            f"Area output field already exists: {cleaned_field!r}.",
        )

    _require_polygon_geometry(frame, operation="Area calculation")

    result = frame.copy()
    geometry = cast(gpd.GeoSeries, result.geometry)
    area_values = geometry.area.astype(float)
    result[cleaned_field] = area_values
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return GeometryAreaResult(
        source=str(source_path),
        output=str(output_path),
        feature_count=len(result),
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        output_field=cleaned_field,
        minimum_area_m2=float(area_values.min()),
        maximum_area_m2=float(area_values.max()),
        total_area_m2=float(area_values.sum()),
    )


def buffer_by_distance_field(
    source: str | Path,
    output: str | Path,
    *,
    distance_field: str,
    crs: str,
    quadrant_segments: int = 16,
    overwrite: bool = False,
) -> BufferResult:
    """Buffer every feature by a positive, metre-valued attribute field."""
    source_path, frame = _load_valid_dataset(source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(frame, expected_crs)

    if quadrant_segments < 1:
        raise VectorOperationError(
            VectorOperationErrorCode.INVALID_BUFFER_RESOLUTION,
            "quadrant_segments must be at least 1.",
        )
    if distance_field not in frame.columns:
        raise VectorOperationError(
            VectorOperationErrorCode.MISSING_FIELD,
            f"Buffer distance field does not exist: {distance_field!r}.",
        )

    source_distances = cast(pd.Series, frame[distance_field])
    numeric_distances = cast(
        pd.Series,
        pd.to_numeric(source_distances, errors="coerce"),
    )
    missing_or_non_numeric_count = int(numeric_distances.isna().sum())
    if missing_or_non_numeric_count:
        raise VectorOperationError(
            VectorOperationErrorCode.INVALID_DISTANCE_VALUES,
            "Buffer distance field contains "
            f"{missing_or_non_numeric_count} null or non-numeric values.",
        )
    distance_values = [float(value) for value in numeric_distances.tolist()]
    invalid_count = sum(not isfinite(value) for value in distance_values)
    if invalid_count:
        raise VectorOperationError(
            VectorOperationErrorCode.INVALID_DISTANCE_VALUES,
            f"Buffer distance field contains {invalid_count} non-finite values.",
        )
    non_positive_count = sum(value <= 0 for value in distance_values)
    if non_positive_count:
        raise VectorOperationError(
            VectorOperationErrorCode.NON_POSITIVE_DISTANCE,
            f"Buffer distance field contains {non_positive_count} values that "
            "are not greater than 0 metres.",
        )

    geometry = cast(gpd.GeoSeries, frame.geometry)
    result = frame.copy()
    result = result.set_geometry(
        geometry.buffer(distance_values, resolution=quadrant_segments)
    )
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return BufferResult(
        source=str(source_path),
        output=str(output_path),
        feature_count=len(result),
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        distance_field=distance_field,
        minimum_distance_m=min(distance_values),
        maximum_distance_m=max(distance_values),
        quadrant_segments=quadrant_segments,
    )


def dissolve_coverage_buffers(
    source: str | Path,
    output: str | Path,
    *,
    crs: str,
    method: str = "union_all",
    overwrite: bool = False,
) -> DissolveResult:
    """Union all buffer polygons so overlapping coverage is counted once."""
    if method != "union_all":
        raise VectorOperationError(
            VectorOperationErrorCode.UNSUPPORTED_METHOD,
            "Coverage buffers must use method='union_all'.",
        )
    source_path, frame = _load_valid_dataset(source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(frame, expected_crs)
    _require_polygon_geometry(frame, operation="Coverage dissolve")

    geometry = cast(gpd.GeoSeries, frame.geometry)
    dissolved_geometry = geometry.union_all()
    result = gpd.GeoDataFrame(
        {"geometry": [dissolved_geometry]},
        geometry="geometry",
        crs=expected_crs,
    )
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return DissolveResult(
        source=str(source_path),
        output=str(output_path),
        input_feature_count=len(frame),
        feature_count=len(result),
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        method=method,
    )


def intersect_polygon_datasets(
    left_source: str | Path,
    right_source: str | Path,
    output: str | Path,
    *,
    crs: str,
    how: str = "intersection",
    overwrite: bool = False,
) -> OverlayIntersectionResult:
    """Intersect two polygon layers that share the declared metric CRS."""
    if how != "intersection":
        raise VectorOperationError(
            VectorOperationErrorCode.UNSUPPORTED_OVERLAY,
            "Coverage overlay must use how='intersection'.",
        )
    left_path, left = _load_valid_dataset(left_source)
    right_path, right = _load_valid_dataset(right_source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(left, expected_crs, dataset_label="Left dataset")
    _require_matching_crs(right, expected_crs, dataset_label="Right dataset")
    _require_polygon_geometry(left, operation="Overlay intersection")
    _require_polygon_geometry(right, operation="Overlay intersection")

    result = gpd.overlay(
        left,
        right,
        how="intersection",
        keep_geom_type=True,
    )
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return OverlayIntersectionResult(
        left_source=str(left_path),
        right_source=str(right_path),
        output=str(output_path),
        left_feature_count=len(left),
        right_feature_count=len(right),
        feature_count=len(result),
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        how=how,
    )

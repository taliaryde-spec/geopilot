"""Deterministic vector transformations used only after plan approval."""

from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

import geopandas as gpd
from pyproj import CRS
from pyproj.exceptions import CRSError

from geopilot.models import GeometryAreaResult, ReprojectionResult
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
    actual_crs = cast(CRS, frame.crs)
    if actual_crs != expected_crs:
        raise VectorOperationError(
            VectorOperationErrorCode.CRS_MISMATCH,
            "Dataset CRS does not match the explicitly requested analysis CRS: "
            f"{actual_crs.to_string()} != {expected_crs.to_string()}.",
        )

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

    geometry_types = set(_geometry_type_counts(frame))
    unsupported_types = geometry_types - {"Polygon", "MultiPolygon"}
    if unsupported_types:
        raise VectorOperationError(
            VectorOperationErrorCode.NON_POLYGON_GEOMETRY,
            "Area calculation only accepts Polygon or MultiPolygon geometry; "
            f"received: {', '.join(sorted(unsupported_types))}.",
        )

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

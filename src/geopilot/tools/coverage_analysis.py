"""Deterministic public-service coverage metrics and table operations."""

from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd

from geopilot.models import (
    AttributeJoinResult,
    CoverageMetricsResult,
    RestoreUncoveredResult,
    SpatialJoinCountResult,
)
from geopilot.tools.vector_operations import (
    _geometry_type_counts,
    _load_valid_dataset,
    _parse_crs,
    _require_matching_crs,
    _require_metric_projected_crs,
    _require_polygon_geometry,
    _write_geopackage,
)


class CoverageOperationErrorCode(StrEnum):
    """Stable identifiers for invalid coverage-analysis inputs."""

    MISSING_FIELD = "missing_field"
    NULL_KEY = "null_key"
    DUPLICATE_KEY = "duplicate_key"
    UNKNOWN_KEY = "unknown_key"
    OUTPUT_FIELD_EXISTS = "output_field_exists"
    INVALID_NUMERIC_VALUES = "invalid_numeric_values"
    NON_POSITIVE_TOTAL_AREA = "non_positive_total_area"
    NEGATIVE_POPULATION = "negative_population"
    INCONSISTENT_GROUP_VALUES = "inconsistent_group_values"
    UNSUPPORTED_POPULATION_METHOD = "unsupported_population_method"
    INVALID_FILL_DEFAULTS = "invalid_fill_defaults"
    UNSUPPORTED_JOIN = "unsupported_join"
    UNSUPPORTED_PREDICATE = "unsupported_predicate"
    UNSUPPORTED_AGGREGATION = "unsupported_aggregation"
    INVALID_SUFFIXES = "invalid_suffixes"
    NO_JOIN_FIELDS = "no_join_fields"


class CoverageOperationError(ValueError):
    """Raised when coverage metrics or joins cannot be computed safely."""

    def __init__(self, code: CoverageOperationErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _require_fields(
    frame: gpd.GeoDataFrame,
    fields: list[str],
    *,
    operation: str,
) -> None:
    """Require every named field before an analysis operation."""
    missing = [field for field in fields if field not in frame.columns]
    if missing:
        raise CoverageOperationError(
            CoverageOperationErrorCode.MISSING_FIELD,
            f"{operation} is missing required fields: {', '.join(missing)}.",
        )


def _require_unique_key(
    frame: gpd.GeoDataFrame,
    key_field: str,
    *,
    operation: str,
) -> None:
    """Require a non-null, unique key for deterministic joins."""
    _require_fields(frame, [key_field], operation=operation)
    key_values = cast(pd.Series, frame[key_field])
    null_count = int(key_values.isna().sum())
    if null_count:
        raise CoverageOperationError(
            CoverageOperationErrorCode.NULL_KEY,
            f"{operation} key {key_field!r} contains {null_count} null values.",
        )
    duplicate_count = int(key_values.duplicated().sum())
    if duplicate_count:
        raise CoverageOperationError(
            CoverageOperationErrorCode.DUPLICATE_KEY,
            f"{operation} key {key_field!r} contains {duplicate_count} "
            "duplicate values.",
        )


def _numeric_series(
    frame: gpd.GeoDataFrame,
    field: str,
    *,
    operation: str,
) -> pd.Series:
    """Return finite numeric field values or raise a stable error."""
    _require_fields(frame, [field], operation=operation)
    numeric = cast(pd.Series, pd.to_numeric(frame[field], errors="coerce"))
    invalid_count = int(numeric.isna().sum())
    if invalid_count:
        raise CoverageOperationError(
            CoverageOperationErrorCode.INVALID_NUMERIC_VALUES,
            f"{operation} field {field!r} contains {invalid_count} null or "
            "non-numeric values.",
        )
    non_finite_count = sum(not isfinite(float(value)) for value in numeric.tolist())
    if non_finite_count:
        raise CoverageOperationError(
            CoverageOperationErrorCode.INVALID_NUMERIC_VALUES,
            f"{operation} field {field!r} contains {non_finite_count} "
            "non-finite values.",
        )
    return numeric.astype(float)


def _require_consistent_group_values(
    frame: gpd.GeoDataFrame,
    *,
    key_field: str,
    value_fields: list[str],
) -> None:
    """Ensure target totals do not change across intersection fragments."""
    for field in value_fields:
        unique_counts = cast(
            pd.Series,
            frame.groupby(key_field, dropna=False)[field].nunique(dropna=False),
        )
        if bool((unique_counts > 1).any()):
            raise CoverageOperationError(
                CoverageOperationErrorCode.INCONSISTENT_GROUP_VALUES,
                f"Coverage fragments disagree on field {field!r} within "
                f"the same {key_field!r}.",
            )


def calculate_coverage_metrics(
    source: str | Path,
    output: str | Path,
    *,
    key_field: str,
    intersection_area_field: str,
    total_area_field: str,
    coverage_ratio_field: str,
    population_field: str,
    estimated_covered_population_field: str,
    population_method: str,
    crs: str,
    overwrite: bool = False,
) -> CoverageMetricsResult:
    """Aggregate covered geometry and compute explicit per-target metrics."""
    if population_method != "area_weighted_uniform_density":
        raise CoverageOperationError(
            CoverageOperationErrorCode.UNSUPPORTED_POPULATION_METHOD,
            "Coverage population estimation requires "
            "population_method='area_weighted_uniform_density'.",
        )
    source_path, frame = _load_valid_dataset(source, allow_empty=True)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(frame, expected_crs)
    _require_polygon_geometry(frame, operation="Coverage metrics")
    _require_fields(
        frame,
        [key_field, total_area_field, population_field],
        operation="Coverage metrics",
    )

    output_fields = [
        intersection_area_field,
        coverage_ratio_field,
        estimated_covered_population_field,
    ]
    conflicts = [field for field in output_fields if field in frame.columns]
    if conflicts:
        raise CoverageOperationError(
            CoverageOperationErrorCode.OUTPUT_FIELD_EXISTS,
            "Coverage output fields already exist: " + ", ".join(conflicts) + ".",
        )

    if frame.empty:
        result = frame.copy()
        for field in output_fields:
            result[field] = pd.Series(index=result.index, dtype="float64")
    else:
        key_values = cast(pd.Series, frame[key_field])
        null_key_count = int(key_values.isna().sum())
        if null_key_count:
            raise CoverageOperationError(
                CoverageOperationErrorCode.NULL_KEY,
                f"Coverage key {key_field!r} contains {null_key_count} null values.",
            )
        frame = frame.copy()
        frame[total_area_field] = _numeric_series(
            frame,
            total_area_field,
            operation="Coverage metrics",
        )
        frame[population_field] = _numeric_series(
            frame,
            population_field,
            operation="Coverage metrics",
        )
        if bool((cast(pd.Series, frame[total_area_field]) <= 0).any()):
            raise CoverageOperationError(
                CoverageOperationErrorCode.NON_POSITIVE_TOTAL_AREA,
                f"Coverage total-area field {total_area_field!r} must be "
                "greater than 0.",
            )
        if bool((cast(pd.Series, frame[population_field]) < 0).any()):
            raise CoverageOperationError(
                CoverageOperationErrorCode.NEGATIVE_POPULATION,
                f"Coverage population field {population_field!r} must not be negative.",
            )
        _require_consistent_group_values(
            frame,
            key_field=key_field,
            value_fields=[total_area_field, population_field],
        )
        result = frame.dissolve(
            by=key_field,
            as_index=False,
            aggfunc="first",
        )
        covered_geometry = cast(gpd.GeoSeries, result.geometry)
        result[intersection_area_field] = covered_geometry.area.astype(float)
        result[coverage_ratio_field] = cast(
            pd.Series,
            result[intersection_area_field],
        ) / cast(pd.Series, result[total_area_field])
        result[estimated_covered_population_field] = cast(
            pd.Series,
            result[population_field],
        ) * cast(pd.Series, result[coverage_ratio_field])

    output_path = _write_geopackage(result, output, overwrite=overwrite)
    covered_area = cast(pd.Series, result[intersection_area_field])
    return CoverageMetricsResult(
        source=str(source_path),
        output=str(output_path),
        feature_count=len(result),
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        key_field=key_field,
        intersection_area_field=intersection_area_field,
        total_area_field=total_area_field,
        coverage_ratio_field=coverage_ratio_field,
        population_field=population_field,
        estimated_covered_population_field=estimated_covered_population_field,
        population_method=population_method,
        total_covered_area_m2=float(covered_area.sum()),
    )


def restore_uncovered_features(
    target_source: str | Path,
    metrics_source: str | Path,
    output: str | Path,
    *,
    key_field: str,
    fill_defaults: dict[str, float],
    crs: str,
    overwrite: bool = False,
) -> RestoreUncoveredResult:
    """Left-join metrics to all targets and fill only omitted-target values."""
    if not fill_defaults or any(
        not isfinite(float(value)) for value in fill_defaults.values()
    ):
        raise CoverageOperationError(
            CoverageOperationErrorCode.INVALID_FILL_DEFAULTS,
            "fill_defaults must contain finite numeric values.",
        )
    target_path, target = _load_valid_dataset(target_source)
    metrics_path, metrics = _load_valid_dataset(metrics_source, allow_empty=True)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(target, expected_crs, dataset_label="Target dataset")
    _require_matching_crs(metrics, expected_crs, dataset_label="Metrics dataset")
    _require_polygon_geometry(target, operation="Restore uncovered features")
    _require_polygon_geometry(metrics, operation="Restore uncovered features")
    _require_unique_key(target, key_field, operation="Restore target")
    _require_unique_key(metrics, key_field, operation="Restore metrics")
    metric_fields = list(fill_defaults)
    _require_fields(metrics, metric_fields, operation="Restore metrics")
    conflicts = [field for field in metric_fields if field in target.columns]
    if conflicts:
        raise CoverageOperationError(
            CoverageOperationErrorCode.OUTPUT_FIELD_EXISTS,
            "Target already contains metric fields: " + ", ".join(conflicts) + ".",
        )
    for field in metric_fields:
        metrics[field] = _numeric_series(
            metrics,
            field,
            operation="Restore metrics",
        )

    target_keys = set(cast(pd.Series, target[key_field]).tolist())
    metric_keys = set(cast(pd.Series, metrics[key_field]).tolist())
    unknown_keys = metric_keys - target_keys
    if unknown_keys:
        raise CoverageOperationError(
            CoverageOperationErrorCode.UNKNOWN_KEY,
            f"Metrics contain {len(unknown_keys)} keys absent from the target dataset.",
        )

    metrics_table = cast(
        pd.DataFrame,
        metrics.loc[:, [key_field, *metric_fields]],
    )
    merged = target.merge(
        metrics_table,
        how="left",
        on=key_field,
        validate="one_to_one",
        indicator="_coverage_merge",
    )
    merge_status = cast(pd.Series, merged["_coverage_merge"])
    restored_count = int((merge_status == "left_only").sum())
    merged = merged.drop(columns=["_coverage_merge"])
    for field, default in fill_defaults.items():
        merged[field] = cast(pd.Series, merged[field]).fillna(float(default))
    result = gpd.GeoDataFrame(
        merged,
        geometry=target.geometry.name,
        crs=expected_crs,
    )
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return RestoreUncoveredResult(
        target_source=str(target_path),
        metrics_source=str(metrics_path),
        output=str(output_path),
        feature_count=len(result),
        restored_feature_count=restored_count,
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        key_field=key_field,
        fill_defaults={key: float(value) for key, value in fill_defaults.items()},
    )


def count_spatial_relationships(
    left_source: str | Path,
    right_source: str | Path,
    output: str | Path,
    *,
    key_field: str,
    output_field: str,
    crs: str,
    how: str = "left",
    predicate: str = "intersects",
    aggregation: str = "count",
    left_suffix: str = "left",
    right_suffix: str = "right",
    overwrite: bool = False,
) -> SpatialJoinCountResult:
    """Count right-side geometries related to each left target polygon."""
    if how != "left":
        raise CoverageOperationError(
            CoverageOperationErrorCode.UNSUPPORTED_JOIN,
            "Spatial relationship counts require how='left'.",
        )
    if predicate != "intersects":
        raise CoverageOperationError(
            CoverageOperationErrorCode.UNSUPPORTED_PREDICATE,
            "Current facility counts require predicate='intersects'.",
        )
    if aggregation != "count":
        raise CoverageOperationError(
            CoverageOperationErrorCode.UNSUPPORTED_AGGREGATION,
            "Spatial relationship counts require aggregation='count'.",
        )
    if not left_suffix or not right_suffix or left_suffix == right_suffix:
        raise CoverageOperationError(
            CoverageOperationErrorCode.INVALID_SUFFIXES,
            "Spatial join suffixes must be non-empty and different.",
        )

    left_path, left = _load_valid_dataset(left_source)
    right_path, right = _load_valid_dataset(right_source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(left, expected_crs, dataset_label="Left dataset")
    _require_matching_crs(right, expected_crs, dataset_label="Right dataset")
    _require_polygon_geometry(left, operation="Spatial relationship count")
    _require_unique_key(left, key_field, operation="Spatial relationship count")
    if output_field in left.columns:
        raise CoverageOperationError(
            CoverageOperationErrorCode.OUTPUT_FIELD_EXISTS,
            f"Spatial count output field already exists: {output_field!r}.",
        )

    match_marker = "__geopilot_match__"
    right_geometry = gpd.GeoDataFrame(
        {match_marker: pd.Series(1, index=right.index, dtype=int)},
        geometry=cast(gpd.GeoSeries, right.geometry).copy(),
        crs=expected_crs,
    )
    joined = gpd.sjoin(
        left,
        right_geometry,
        how="left",
        predicate=predicate,
        lsuffix=left_suffix,
        rsuffix=right_suffix,
    )
    matched_rows = cast(pd.Series, joined[match_marker]).notna()
    relationship_count = int(matched_rows.sum())
    counts = cast(
        pd.Series,
        joined.loc[matched_rows].groupby(key_field)[match_marker].count(),
    )
    result = left.copy()
    result[output_field] = (
        cast(pd.Series, result[key_field]).map(counts).fillna(0).astype(int)
    )
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return SpatialJoinCountResult(
        left_source=str(left_path),
        right_source=str(right_path),
        output=str(output_path),
        feature_count=len(result),
        relationship_count=relationship_count,
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        key_field=key_field,
        output_field=output_field,
        predicate=predicate,
    )


def join_coverage_attributes(
    left_source: str | Path,
    right_source: str | Path,
    output: str | Path,
    *,
    left_key: str,
    right_key: str,
    crs: str,
    how: str = "left",
    left_suffix: str = "coverage",
    right_suffix: str = "count",
    overwrite: bool = False,
) -> AttributeJoinResult:
    """Bring new right-side attributes onto left coverage polygons by key."""
    if how != "left":
        raise CoverageOperationError(
            CoverageOperationErrorCode.UNSUPPORTED_JOIN,
            "Coverage attribute joins require how='left'.",
        )
    if not left_suffix or not right_suffix or left_suffix == right_suffix:
        raise CoverageOperationError(
            CoverageOperationErrorCode.INVALID_SUFFIXES,
            "Attribute join suffixes must be non-empty and different.",
        )
    left_path, left = _load_valid_dataset(left_source)
    right_path, right = _load_valid_dataset(right_source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(left, expected_crs, dataset_label="Left dataset")
    _require_matching_crs(right, expected_crs, dataset_label="Right dataset")
    _require_unique_key(left, left_key, operation="Coverage attribute join")
    _require_unique_key(right, right_key, operation="Coverage attribute join")

    right_fields = [
        field
        for field in right.columns
        if field not in {right.geometry.name, right_key} and field not in left.columns
    ]
    if not right_fields:
        raise CoverageOperationError(
            CoverageOperationErrorCode.NO_JOIN_FIELDS,
            "Right dataset has no new attributes to join onto the coverage result.",
        )
    right_table = cast(
        pd.DataFrame,
        right.loc[:, [right_key, *right_fields]],
    )
    merged = left.merge(
        right_table,
        how="left",
        left_on=left_key,
        right_on=right_key,
        suffixes=(left_suffix, right_suffix),
        validate="one_to_one",
        indicator="_attribute_merge",
    )
    merge_status = cast(pd.Series, merged["_attribute_merge"])
    matched_count = int((merge_status == "both").sum())
    unmatched_count = int((merge_status == "left_only").sum())
    merged = merged.drop(columns=["_attribute_merge"])
    if left_key != right_key:
        merged = merged.drop(columns=[right_key])
    result = gpd.GeoDataFrame(
        merged,
        geometry=left.geometry.name,
        crs=expected_crs,
    )
    output_path = _write_geopackage(result, output, overwrite=overwrite)
    return AttributeJoinResult(
        left_source=str(left_path),
        right_source=str(right_path),
        output=str(output_path),
        feature_count=len(result),
        matched_feature_count=matched_count,
        unmatched_feature_count=unmatched_count,
        geometry_types=_geometry_type_counts(result),
        crs=expected_crs.to_string(),
        left_key=left_key,
        right_key=right_key,
    )

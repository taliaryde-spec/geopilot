"""Validate and export grounded outputs from deterministic GIS analysis."""

from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import cast
from uuid import uuid4

import geopandas as gpd
import pandas as pd

from geopilot.models import (
    CoverageReportResult,
    CoverageValidationResult,
    GeoJsonExportResult,
)
from geopilot.tools.vector_operations import (
    _load_valid_dataset,
    _parse_crs,
    _require_matching_crs,
    _require_metric_projected_crs,
    _write_geopackage,
)


class ResultOutputErrorCode(StrEnum):
    """Stable identifiers for validation and export failures."""

    MISSING_FIELD = "missing_field"
    INVALID_CHECKS = "invalid_checks"
    VALIDATION_FAILED = "validation_failed"
    OUTPUT_EXISTS = "output_exists"
    UNSUPPORTED_OUTPUT_FORMAT = "unsupported_output_format"
    INVALID_OUTPUT_CRS = "invalid_output_crs"


class ResultOutputError(ValueError):
    """Raised when validated analysis output cannot be produced safely."""

    def __init__(
        self,
        code: ResultOutputErrorCode,
        message: str,
        *,
        failed_checks: list[str] | None = None,
    ) -> None:
        self.code = code
        self.failed_checks = failed_checks or []
        super().__init__(message)


REQUIRED_RESULT_CHECKS = {
    "valid_geometry",
    "no_null_metrics",
    "coverage_ratio_between_0_and_1",
    "covered_population_not_above_population",
}


def _require_fields(
    frame: gpd.GeoDataFrame,
    fields: list[str],
    *,
    operation: str,
) -> None:
    """Require all fields used by validation or reporting."""
    missing = [field for field in fields if field not in frame.columns]
    if missing:
        raise ResultOutputError(
            ResultOutputErrorCode.MISSING_FIELD,
            f"{operation} is missing required fields: {', '.join(missing)}.",
        )


def _numeric_series(
    frame: gpd.GeoDataFrame,
    field: str,
    *,
    operation: str,
) -> pd.Series:
    """Return numeric values while preserving invalid entries as NaN."""
    _require_fields(frame, [field], operation=operation)
    return cast(pd.Series, pd.to_numeric(frame[field], errors="coerce")).astype(float)


def _prepare_output_file(
    output: str | Path,
    *,
    required_suffix: str,
    overwrite: bool,
) -> Path:
    """Resolve one output file and prevent accidental replacement."""
    output_path = Path(output).resolve()
    if output_path.suffix.lower() != required_suffix:
        raise ResultOutputError(
            ResultOutputErrorCode.UNSUPPORTED_OUTPUT_FORMAT,
            f"Output must use the {required_suffix} extension: {output_path}",
        )
    if output_path.exists() and not overwrite:
        raise ResultOutputError(
            ResultOutputErrorCode.OUTPUT_EXISTS,
            f"Output already exists and overwrite is disabled: {output_path}",
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def validate_coverage_result(
    source: str | Path,
    output: str | Path,
    *,
    checks: list[str],
    covered_area_field: str,
    coverage_ratio_field: str,
    population_field: str,
    estimated_covered_population_field: str,
    facility_count_field: str,
    crs: str,
    overwrite: bool = False,
) -> CoverageValidationResult:
    """Run canonical checks and persist a checkpoint only when all pass."""
    provided_checks = set(checks)
    if provided_checks != REQUIRED_RESULT_CHECKS or len(checks) != len(
        REQUIRED_RESULT_CHECKS
    ):
        raise ResultOutputError(
            ResultOutputErrorCode.INVALID_CHECKS,
            "Result checks must contain each canonical check exactly once.",
        )
    source_path, frame = _load_valid_dataset(source)
    expected_crs = _parse_crs(crs, label="crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(frame, expected_crs)
    metric_fields = [
        covered_area_field,
        coverage_ratio_field,
        estimated_covered_population_field,
        facility_count_field,
    ]
    _require_fields(
        frame,
        [*metric_fields, population_field],
        operation="Coverage result validation",
    )

    geometry = cast(gpd.GeoSeries, frame.geometry)
    valid_geometry = bool(
        (~geometry.isna() & ~geometry.is_empty & geometry.is_valid).all()
    )
    numeric_metrics = {
        field: _numeric_series(
            frame,
            field,
            operation="Coverage result validation",
        )
        for field in metric_fields
    }
    no_null_metrics = all(
        values.notna().all()
        and all(isfinite(float(value)) for value in values.tolist())
        for values in numeric_metrics.values()
    )
    coverage_ratio = numeric_metrics[coverage_ratio_field]
    population = _numeric_series(
        frame,
        population_field,
        operation="Coverage result validation",
    )
    covered_population = numeric_metrics[estimated_covered_population_field]
    ratio_in_range = bool(
        coverage_ratio.notna().all()
        and ((coverage_ratio >= 0) & (coverage_ratio <= 1)).all()
    )
    population_in_range = bool(
        population.notna().all()
        and covered_population.notna().all()
        and (covered_population >= 0).all()
        and (covered_population <= population + 1e-9).all()
    )
    check_results = {
        "valid_geometry": valid_geometry,
        "no_null_metrics": no_null_metrics,
        "coverage_ratio_between_0_and_1": ratio_in_range,
        "covered_population_not_above_population": population_in_range,
    }
    failed_checks = [name for name, passed in check_results.items() if not passed]
    if failed_checks:
        raise ResultOutputError(
            ResultOutputErrorCode.VALIDATION_FAILED,
            "Coverage result failed checks: " + ", ".join(failed_checks) + ".",
            failed_checks=failed_checks,
        )

    output_path = _write_geopackage(frame, output, overwrite=overwrite)
    return CoverageValidationResult(
        source=str(source_path),
        output=str(output_path),
        feature_count=len(frame),
        crs=expected_crs.to_string(),
        checks=check_results,
        passed=True,
    )


def export_web_geojson(
    source: str | Path,
    output: str | Path,
    *,
    output_crs: str = "EPSG:4326",
    overwrite: bool = False,
) -> GeoJsonExportResult:
    """Export validated results to interoperable WGS 84 GeoJSON."""
    target_crs = _parse_crs(output_crs, label="output_crs")
    if target_crs.to_epsg() != 4326:
        raise ResultOutputError(
            ResultOutputErrorCode.INVALID_OUTPUT_CRS,
            "Web GeoJSON output requires output_crs='EPSG:4326'.",
        )
    source_path, frame = _load_valid_dataset(source)
    source_crs = frame.crs
    if source_crs is None:
        raise ResultOutputError(
            ResultOutputErrorCode.INVALID_OUTPUT_CRS,
            "Source dataset has no CRS and cannot be exported safely.",
        )
    output_path = _prepare_output_file(
        output,
        required_suffix=".geojson",
        overwrite=overwrite,
    )
    exported = frame.to_crs(target_crs)
    temporary_path = output_path.with_name(
        f".{output_path.stem}-{uuid4().hex}.tmp.geojson"
    )
    try:
        exported.to_file(temporary_path, driver="GeoJSON", index=False)
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    geometry = cast(gpd.GeoSeries, exported.geometry)
    bounds = (
        tuple(float(value) for value in geometry.total_bounds)
        if not exported.empty
        else None
    )
    return GeoJsonExportResult(
        source=str(source_path),
        output=str(output_path),
        feature_count=len(exported),
        source_crs=source_crs.to_string(),
        output_crs=target_crs.to_string(),
        bounds=cast(tuple[float, float, float, float] | None, bounds),
    )


def generate_coverage_report(
    source: str | Path,
    output: str | Path,
    *,
    neighborhood_key_field: str,
    population_field: str,
    covered_area_field: str,
    coverage_ratio_field: str,
    estimated_covered_population_field: str,
    facility_count_field: str,
    analysis_crs: str,
    export_crs: str,
    overwrite: bool = False,
) -> CoverageReportResult:
    """Generate a reproducible Markdown report grounded in validated rows."""
    source_path, frame = _load_valid_dataset(source)
    expected_crs = _parse_crs(analysis_crs, label="analysis_crs")
    _require_metric_projected_crs(expected_crs)
    _require_matching_crs(frame, expected_crs)
    export = _parse_crs(export_crs, label="export_crs")
    if export.to_epsg() != 4326:
        raise ResultOutputError(
            ResultOutputErrorCode.INVALID_OUTPUT_CRS,
            "Coverage report export_crs must be EPSG:4326.",
        )
    fields = [
        neighborhood_key_field,
        population_field,
        covered_area_field,
        coverage_ratio_field,
        estimated_covered_population_field,
        facility_count_field,
    ]
    _require_fields(frame, fields, operation="Coverage report")
    population = _numeric_series(frame, population_field, operation="Coverage report")
    covered_population = _numeric_series(
        frame,
        estimated_covered_population_field,
        operation="Coverage report",
    )
    coverage_ratio = _numeric_series(
        frame,
        coverage_ratio_field,
        operation="Coverage report",
    )
    covered_area = _numeric_series(
        frame,
        covered_area_field,
        operation="Coverage report",
    )
    facility_count = _numeric_series(
        frame,
        facility_count_field,
        operation="Coverage report",
    )
    total_population = float(population.sum())
    total_covered_population = float(covered_population.sum())
    population_coverage_ratio = (
        total_covered_population / total_population if total_population > 0 else 0.0
    )
    zero_coverage_count = int((coverage_ratio == 0).sum())
    facility_relationship_count = int(facility_count.sum())
    output_path = _prepare_output_file(
        output,
        required_suffix=".md",
        overwrite=overwrite,
    )
    report = f"""# GeoPilot 公共服务覆盖分析报告

## 分析口径

- 分析坐标系：{expected_crs.to_string()}（距离单位：米，面积单位：平方米）
- Web 导出坐标系：{export.to_string()}
- 社区标识字段：`{neighborhood_key_field}`
- 覆盖率公式：`{covered_area_field} / 社区总面积`
- 覆盖人口公式：`{population_field} × {coverage_ratio_field}`
- 人口假设：社区内部人口均匀分布（area_weighted_uniform_density）

## 结果摘要

- 社区数量：{len(frame)}
- 零覆盖社区数量：{zero_coverage_count}
- 覆盖总面积：{float(covered_area.sum()):.2f} 平方米
- 总人口：{total_population:.2f}
- 估算覆盖人口：{total_covered_population:.2f}
- 人口加权覆盖率：{population_coverage_ratio:.4f}
- 社区—设施空间匹配数量：{facility_relationship_count}

## 局限性

- 覆盖人口基于社区内部人口均匀分布假设，并非人口点位的直接统计。
- 位于社区边界上的设施使用 `intersects` 判断时可能计入多个社区。
- 服务范围来自设施字段中的米制服务半径，不代表实际路网可达时间。
"""
    temporary_path = output_path.with_name(f".{output_path.stem}-{uuid4().hex}.tmp.md")
    try:
        temporary_path.write_text(report, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return CoverageReportResult(
        source=str(source_path),
        output=str(output_path),
        neighborhood_count=len(frame),
        zero_coverage_count=zero_coverage_count,
        total_population=total_population,
        estimated_covered_population=total_covered_population,
        population_coverage_ratio=population_coverage_ratio,
        facility_relationship_count=facility_relationship_count,
        analysis_crs=expected_crs.to_string(),
        export_crs=export.to_string(),
    )

"""Bind compiled operations to deterministic GIS tool functions."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from geopilot.execution.models import CompiledStep, StepDispatchResult
from geopilot.planning.models import AnalysisOperation
from geopilot.tools.coverage_analysis import (
    calculate_coverage_metrics,
    count_spatial_relationships,
    join_coverage_attributes,
    restore_uncovered_features,
)
from geopilot.tools.result_outputs import (
    export_web_geojson,
    generate_coverage_report,
    validate_coverage_result,
)
from geopilot.tools.vector_operations import (
    buffer_by_distance_field,
    calculate_polygon_area,
    dissolve_coverage_buffers,
    intersect_polygon_datasets,
    reproject_vector_dataset,
)


class StepDispatchErrorCode(StrEnum):
    """Stable identifiers for unsafe compiled tool calls."""

    INVALID_INPUT_COUNT = "invalid_input_count"
    MISSING_PARAMETER = "missing_parameter"
    INVALID_PARAMETER_TYPE = "invalid_parameter_type"
    UNKNOWN_PARAMETER = "unknown_parameter"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INVALID_TOOL_RESULT = "invalid_tool_result"


class StepDispatchError(ValueError):
    """Raised before or after a tool call when its contract is invalid."""

    def __init__(
        self,
        code: StepDispatchErrorCode,
        message: str,
        *,
        step_id: int,
    ) -> None:
        self.code = code
        self.step_id = step_id
        super().__init__(message)


_EXPECTED_INPUT_COUNTS = {
    AnalysisOperation.REPROJECT: 1,
    AnalysisOperation.CALCULATE_GEOMETRY_AREA: 1,
    AnalysisOperation.BUFFER: 1,
    AnalysisOperation.DISSOLVE: 1,
    AnalysisOperation.OVERLAY_INTERSECTION: 2,
    AnalysisOperation.CALCULATE_COVERAGE_METRICS: 1,
    AnalysisOperation.RESTORE_UNCOVERED_FEATURES: 2,
    AnalysisOperation.SPATIAL_JOIN: 2,
    AnalysisOperation.ATTRIBUTE_JOIN: 2,
    AnalysisOperation.VALIDATE_RESULT: 1,
    AnalysisOperation.EXPORT_GEOJSON: 1,
    AnalysisOperation.GENERATE_REPORT: 1,
}


def _require_inputs(step: CompiledStep, inputs: list[Path]) -> None:
    expected = _EXPECTED_INPUT_COUNTS.get(step.operation)
    if expected is None or len(inputs) != expected:
        raise StepDispatchError(
            StepDispatchErrorCode.INVALID_INPUT_COUNT,
            f"Operation {step.operation.value!r} requires {expected} input(s), "
            f"received {len(inputs)}.",
            step_id=step.step_id,
        )


def _require_parameter_names(
    step: CompiledStep,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(name for name in required if name not in step.parameters)
    if missing:
        raise StepDispatchError(
            StepDispatchErrorCode.MISSING_PARAMETER,
            "Missing required parameters for "
            f"{step.operation.value!r}: {', '.join(missing)}.",
            step_id=step.step_id,
        )
    unknown = sorted(set(step.parameters) - allowed)
    if unknown:
        raise StepDispatchError(
            StepDispatchErrorCode.UNKNOWN_PARAMETER,
            f"Unknown parameters for {step.operation.value!r}: {', '.join(unknown)}.",
            step_id=step.step_id,
        )


def _string(step: CompiledStep, name: str) -> str:
    value = step.parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise StepDispatchError(
            StepDispatchErrorCode.INVALID_PARAMETER_TYPE,
            f"Parameter {name!r} must be a non-empty string.",
            step_id=step.step_id,
        )
    return value


def _integer(step: CompiledStep, name: str) -> int:
    value = step.parameters.get(name)
    if type(value) is not int:
        raise StepDispatchError(
            StepDispatchErrorCode.INVALID_PARAMETER_TYPE,
            f"Parameter {name!r} must be an integer.",
            step_id=step.step_id,
        )
    return value


def _string_list(step: CompiledStep, name: str) -> list[str]:
    value = step.parameters.get(name)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise StepDispatchError(
            StepDispatchErrorCode.INVALID_PARAMETER_TYPE,
            f"Parameter {name!r} must be a non-empty list of strings.",
            step_id=step.step_id,
        )
    return value


def _float_dictionary(step: CompiledStep, name: str) -> dict[str, float]:
    value = step.parameters.get(name)
    if not isinstance(value, dict) or not value:
        raise StepDispatchError(
            StepDispatchErrorCode.INVALID_PARAMETER_TYPE,
            f"Parameter {name!r} must be a non-empty numeric object.",
            step_id=step.step_id,
        )
    converted: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, int | float):
            raise StepDispatchError(
                StepDispatchErrorCode.INVALID_PARAMETER_TYPE,
                f"Parameter {name!r} must be a non-empty numeric object.",
                step_id=step.step_id,
            )
        converted[key] = float(item)
    return converted


def _normalize_result(step: CompiledStep, result: BaseModel) -> StepDispatchResult:
    metadata = result.model_dump(mode="json")
    output = metadata.get("output")
    if not isinstance(output, str) or not output:
        raise StepDispatchError(
            StepDispatchErrorCode.INVALID_TOOL_RESULT,
            f"Tool for {step.operation.value!r} returned no output path.",
            step_id=step.step_id,
        )
    return StepDispatchResult(output=output, metadata=metadata)


def dispatch_step(
    step: CompiledStep,
    inputs: list[Path],
    output: Path,
) -> StepDispatchResult:
    """Execute one compiled operation using its exact deterministic tool."""
    _require_inputs(step, inputs)
    result: BaseModel

    if step.operation is AnalysisOperation.REPROJECT:
        _require_parameter_names(
            step,
            required={"target_crs"},
            optional={"longitude_column", "latitude_column"},
        )
        result = reproject_vector_dataset(
            inputs[0],
            output,
            target_crs=_string(step, "target_crs"),
            longitude_column=str(step.parameters.get("longitude_column", "longitude")),
            latitude_column=str(step.parameters.get("latitude_column", "latitude")),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.CALCULATE_GEOMETRY_AREA:
        _require_parameter_names(
            step,
            required={"output_field", "unit", "crs"},
        )
        result = calculate_polygon_area(
            inputs[0],
            output,
            output_field=_string(step, "output_field"),
            crs=_string(step, "crs"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.BUFFER:
        _require_parameter_names(
            step,
            required={"distance_field", "unit", "crs"},
            optional={"quadrant_segments"},
        )
        result = buffer_by_distance_field(
            inputs[0],
            output,
            distance_field=_string(step, "distance_field"),
            crs=_string(step, "crs"),
            quadrant_segments=(
                _integer(step, "quadrant_segments")
                if "quadrant_segments" in step.parameters
                else 16
            ),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.DISSOLVE:
        _require_parameter_names(step, required={"method", "crs"})
        result = dissolve_coverage_buffers(
            inputs[0],
            output,
            crs=_string(step, "crs"),
            method=_string(step, "method"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.OVERLAY_INTERSECTION:
        _require_parameter_names(step, required={"how", "crs"})
        result = intersect_polygon_datasets(
            inputs[0],
            inputs[1],
            output,
            crs=_string(step, "crs"),
            how=_string(step, "how"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.CALCULATE_COVERAGE_METRICS:
        required = {
            "key_field",
            "intersection_area_field",
            "total_area_field",
            "coverage_ratio_field",
            "population_field",
            "estimated_covered_population_field",
            "population_method",
            "crs",
        }
        _require_parameter_names(step, required=required)
        result = calculate_coverage_metrics(
            inputs[0],
            output,
            key_field=_string(step, "key_field"),
            intersection_area_field=_string(step, "intersection_area_field"),
            total_area_field=_string(step, "total_area_field"),
            coverage_ratio_field=_string(step, "coverage_ratio_field"),
            population_field=_string(step, "population_field"),
            estimated_covered_population_field=_string(
                step, "estimated_covered_population_field"
            ),
            population_method=_string(step, "population_method"),
            crs=_string(step, "crs"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.RESTORE_UNCOVERED_FEATURES:
        _require_parameter_names(
            step,
            required={"key_field", "fill_defaults", "crs"},
        )
        result = restore_uncovered_features(
            inputs[0],
            inputs[1],
            output,
            key_field=_string(step, "key_field"),
            fill_defaults=_float_dictionary(step, "fill_defaults"),
            crs=_string(step, "crs"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.SPATIAL_JOIN:
        required = {
            "key_field",
            "output_field",
            "crs",
            "how",
            "predicate",
            "aggregation",
            "left_suffix",
            "right_suffix",
        }
        _require_parameter_names(step, required=required)
        result = count_spatial_relationships(
            inputs[0],
            inputs[1],
            output,
            key_field=_string(step, "key_field"),
            output_field=_string(step, "output_field"),
            crs=_string(step, "crs"),
            how=_string(step, "how"),
            predicate=_string(step, "predicate"),
            aggregation=_string(step, "aggregation"),
            left_suffix=_string(step, "left_suffix"),
            right_suffix=_string(step, "right_suffix"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.ATTRIBUTE_JOIN:
        required = {
            "left_key",
            "right_key",
            "crs",
            "how",
            "left_suffix",
            "right_suffix",
        }
        _require_parameter_names(step, required=required)
        result = join_coverage_attributes(
            inputs[0],
            inputs[1],
            output,
            left_key=_string(step, "left_key"),
            right_key=_string(step, "right_key"),
            crs=_string(step, "crs"),
            how=_string(step, "how"),
            left_suffix=_string(step, "left_suffix"),
            right_suffix=_string(step, "right_suffix"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.VALIDATE_RESULT:
        required = {
            "checks",
            "covered_area_field",
            "coverage_ratio_field",
            "population_field",
            "estimated_covered_population_field",
            "facility_count_field",
            "crs",
        }
        _require_parameter_names(step, required=required)
        result = validate_coverage_result(
            inputs[0],
            output,
            checks=_string_list(step, "checks"),
            covered_area_field=_string(step, "covered_area_field"),
            coverage_ratio_field=_string(step, "coverage_ratio_field"),
            population_field=_string(step, "population_field"),
            estimated_covered_population_field=_string(
                step, "estimated_covered_population_field"
            ),
            facility_count_field=_string(step, "facility_count_field"),
            crs=_string(step, "crs"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.EXPORT_GEOJSON:
        _require_parameter_names(step, required={"output_crs"})
        result = export_web_geojson(
            inputs[0],
            output,
            output_crs=_string(step, "output_crs"),
            overwrite=True,
        )
    elif step.operation is AnalysisOperation.GENERATE_REPORT:
        required = {
            "neighborhood_key_field",
            "population_field",
            "covered_area_field",
            "coverage_ratio_field",
            "estimated_covered_population_field",
            "facility_count_field",
            "analysis_crs",
            "export_crs",
        }
        _require_parameter_names(step, required=required)
        result = generate_coverage_report(
            inputs[0],
            output,
            neighborhood_key_field=_string(step, "neighborhood_key_field"),
            population_field=_string(step, "population_field"),
            covered_area_field=_string(step, "covered_area_field"),
            coverage_ratio_field=_string(step, "coverage_ratio_field"),
            estimated_covered_population_field=_string(
                step, "estimated_covered_population_field"
            ),
            facility_count_field=_string(step, "facility_count_field"),
            analysis_crs=_string(step, "analysis_crs"),
            export_crs=_string(step, "export_crs"),
            overwrite=True,
        )
    else:
        raise StepDispatchError(
            StepDispatchErrorCode.UNSUPPORTED_OPERATION,
            f"Operation has no deterministic dispatcher: {step.operation.value}",
            step_id=step.step_id,
        )

    return _normalize_result(step, result)

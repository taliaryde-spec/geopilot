"""Semantic guardrails for model-generated geospatial analysis plans."""

from enum import StrEnum
from typing import Any

from geopilot.planning.models import AnalysisOperation, AnalysisPlanProposal


class PlanSemanticErrorCode(StrEnum):
    """Stable identifiers for unsafe or incomplete plan semantics."""

    INVALID_OPERATION_PARAMETERS = "invalid_operation_parameters"
    INVALID_COVERAGE_SEQUENCE = "invalid_coverage_sequence"
    MISSING_AREA_LINEAGE = "missing_area_lineage"
    MISSING_UNCOVERED_RESTORE = "missing_uncovered_restore"
    MISSING_RESULT_JOIN = "missing_result_join"


class PlanSemanticError(ValueError):
    """Raised when a structurally valid plan is unsafe to execute."""

    def __init__(self, code: PlanSemanticErrorCode, message: str) -> None:
        """Store a stable code alongside an actionable correction."""
        self.code = code
        super().__init__(message)


def _require_parameter(
    parameters: dict[str, Any],
    name: str,
    *,
    operation: AnalysisOperation,
) -> Any:
    """Return one non-empty operation parameter or raise a stable error."""
    value = parameters.get(name)
    if value is None or value == "" or value == []:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            f"Operation {operation.value!r} requires parameter {name!r}.",
        )
    return value


def _validate_reproject(parameters: dict[str, Any]) -> None:
    _require_parameter(
        parameters,
        "target_crs",
        operation=AnalysisOperation.REPROJECT,
    )


def _validate_geometry_area(parameters: dict[str, Any]) -> None:
    _require_parameter(
        parameters,
        "output_field",
        operation=AnalysisOperation.CALCULATE_GEOMETRY_AREA,
    )
    unit = _require_parameter(
        parameters,
        "unit",
        operation=AnalysisOperation.CALCULATE_GEOMETRY_AREA,
    )
    if unit != "square_metre":
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            "Operation 'calculate_geometry_area' requires unit='square_metre'.",
        )
    _require_parameter(
        parameters,
        "crs",
        operation=AnalysisOperation.CALCULATE_GEOMETRY_AREA,
    )


def _validate_buffer(parameters: dict[str, Any]) -> None:
    issues: list[str] = []
    has_distance_field = bool(parameters.get("distance_field"))
    if not has_distance_field:
        issues.append(
            "Operation 'buffer' requires parameter 'distance_field'; constant "
            "distance buffers are not supported by the current executor."
        )
    unit = parameters.get("unit")
    if unit is None or unit == "":
        issues.append("Operation 'buffer' requires parameter 'unit'.")
    elif unit != "metre":
        issues.append("Operation 'buffer' requires unit='metre'.")
    if not parameters.get("crs"):
        issues.append("Operation 'buffer' requires parameter 'crs'.")
    if issues:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            " ".join(issues),
        )


def _validate_dissolve(parameters: dict[str, Any]) -> None:
    method = _require_parameter(
        parameters,
        "method",
        operation=AnalysisOperation.DISSOLVE,
    )
    if method != "union_all":
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            "Coverage buffers must use dissolve method='union_all' to prevent "
            "overlap double-counting.",
        )
    _require_parameter(
        parameters,
        "crs",
        operation=AnalysisOperation.DISSOLVE,
    )


def _validate_overlay(parameters: dict[str, Any]) -> None:
    how = _require_parameter(
        parameters,
        "how",
        operation=AnalysisOperation.OVERLAY_INTERSECTION,
    )
    if how != "intersection":
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            "Operation 'overlay_intersection' requires how='intersection'.",
        )
    _require_parameter(
        parameters,
        "crs",
        operation=AnalysisOperation.OVERLAY_INTERSECTION,
    )


def _validate_spatial_join(parameters: dict[str, Any]) -> None:
    issues: list[str] = []
    if "join_type" in parameters:
        issues.append(
            "Operation 'spatial_join' must separate 'how' from 'predicate'; "
            "do not use the ambiguous parameter 'join_type'."
        )
    how = parameters.get("how")
    if how is None or how == "":
        issues.append("Operation 'spatial_join' requires parameter 'how'.")
    elif how != "left":
        issues.append("Operation 'spatial_join' requires how='left'.")
    predicate = parameters.get("predicate")
    if predicate is not None and predicate != "intersects":
        issues.append("Operation 'spatial_join' requires predicate='intersects'.")
    aggregation = parameters.get("aggregation")
    if aggregation is not None and aggregation != "count":
        issues.append("Operation 'spatial_join' requires aggregation='count'.")
    for name in (
        "predicate",
        "aggregation",
        "key_field",
        "output_field",
        "crs",
        "left_suffix",
        "right_suffix",
    ):
        if not parameters.get(name):
            issues.append(f"Operation 'spatial_join' requires parameter {name!r}.")
    if issues:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            " ".join(issues),
        )


def _validate_coverage_metrics(parameters: dict[str, Any]) -> None:
    required_parameters = (
        "key_field",
        "intersection_area_field",
        "total_area_field",
        "coverage_ratio_field",
        "population_field",
        "estimated_covered_population_field",
        "population_method",
        "crs",
    )
    missing_parameters = [
        name for name in required_parameters if not parameters.get(name)
    ]
    issues = []
    if missing_parameters:
        joined_names = ", ".join(repr(name) for name in missing_parameters)
        issues.append(
            "Operation 'calculate_coverage_metrics' requires parameters: "
            f"{joined_names}."
        )
    population_method = parameters.get("population_method")
    if (
        population_method is not None
        and population_method != "area_weighted_uniform_density"
    ):
        issues.append(
            "Coverage population estimation must explicitly use "
            "population_method='area_weighted_uniform_density'."
        )
    if issues:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            " ".join(issues),
        )


def _validate_attribute_join(parameters: dict[str, Any]) -> None:
    issues: list[str] = []
    how = parameters.get("how")
    if how != "left":
        issues.append("Operation 'attribute_join' requires how='left'.")
    for name in (
        "left_key",
        "right_key",
        "crs",
        "left_suffix",
        "right_suffix",
    ):
        if not parameters.get(name):
            issues.append(f"Operation 'attribute_join' requires parameter {name!r}.")
    if issues:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            " ".join(issues),
        )


def _validate_restore_uncovered(parameters: dict[str, Any]) -> None:
    issues: list[str] = []
    if not parameters.get("key_field"):
        issues.append(
            "Operation 'restore_uncovered_features' requires parameter 'key_field'."
        )
    if not parameters.get("crs"):
        issues.append(
            "Operation 'restore_uncovered_features' requires parameter 'crs'."
        )
    fill_defaults = parameters.get("fill_defaults")
    if not isinstance(fill_defaults, dict) or not fill_defaults:
        issues.append(
            "Operation 'restore_uncovered_features' requires a non-empty "
            "'fill_defaults' object."
        )
    if issues:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            " ".join(issues),
        )


def _validate_result(parameters: dict[str, Any]) -> None:
    checks = _require_parameter(
        parameters,
        "checks",
        operation=AnalysisOperation.VALIDATE_RESULT,
    )
    if not isinstance(checks, list) or not all(
        isinstance(check, str) and check for check in checks
    ):
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            "Operation 'validate_result' checks must be a non-empty list of names.",
        )
    required_checks = {
        "valid_geometry",
        "no_null_metrics",
        "coverage_ratio_between_0_and_1",
        "covered_population_not_above_population",
    }
    provided_checks = set(checks)
    missing_checks = required_checks - provided_checks
    unsupported_checks = provided_checks - required_checks
    issues: list[str] = []
    if missing_checks:
        issues.append(
            "Missing required result checks: " + ", ".join(sorted(missing_checks)) + "."
        )
    if unsupported_checks:
        issues.append(
            "Unsupported result checks: " + ", ".join(sorted(unsupported_checks)) + "."
        )
    if issues:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            " ".join(issues),
        )
    for name in (
        "covered_area_field",
        "coverage_ratio_field",
        "population_field",
        "estimated_covered_population_field",
        "facility_count_field",
        "crs",
    ):
        _require_parameter(
            parameters,
            name,
            operation=AnalysisOperation.VALIDATE_RESULT,
        )


def _validate_export_geojson(parameters: dict[str, Any]) -> None:
    output_crs = _require_parameter(
        parameters,
        "output_crs",
        operation=AnalysisOperation.EXPORT_GEOJSON,
    )
    if output_crs != "EPSG:4326":
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            "GeoJSON output must use output_crs='EPSG:4326' for interoperable "
            "web mapping; metric calculations remain in the analysis CRS.",
        )


def _validate_generate_report(parameters: dict[str, Any]) -> None:
    for name in (
        "neighborhood_key_field",
        "population_field",
        "covered_area_field",
        "coverage_ratio_field",
        "estimated_covered_population_field",
        "facility_count_field",
        "analysis_crs",
        "export_crs",
    ):
        _require_parameter(
            parameters,
            name,
            operation=AnalysisOperation.GENERATE_REPORT,
        )
    if parameters.get("export_crs") != "EPSG:4326":
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            "Coverage report requires export_crs='EPSG:4326'.",
        )


_OPERATION_VALIDATORS = {
    AnalysisOperation.REPROJECT: _validate_reproject,
    AnalysisOperation.CALCULATE_GEOMETRY_AREA: _validate_geometry_area,
    AnalysisOperation.BUFFER: _validate_buffer,
    AnalysisOperation.DISSOLVE: _validate_dissolve,
    AnalysisOperation.OVERLAY_INTERSECTION: _validate_overlay,
    AnalysisOperation.SPATIAL_JOIN: _validate_spatial_join,
    AnalysisOperation.CALCULATE_COVERAGE_METRICS: _validate_coverage_metrics,
    AnalysisOperation.RESTORE_UNCOVERED_FEATURES: _validate_restore_uncovered,
    AnalysisOperation.ATTRIBUTE_JOIN: _validate_attribute_join,
    AnalysisOperation.VALIDATE_RESULT: _validate_result,
    AnalysisOperation.EXPORT_GEOJSON: _validate_export_geojson,
    AnalysisOperation.GENERATE_REPORT: _validate_generate_report,
}

_EXPECTED_INPUT_COUNTS = {
    AnalysisOperation.INSPECT_DATASET: 1,
    AnalysisOperation.RECOMMEND_METRIC_CRS: 1,
    AnalysisOperation.REPROJECT: 1,
    AnalysisOperation.CALCULATE_GEOMETRY_AREA: 1,
    AnalysisOperation.BUFFER: 1,
    AnalysisOperation.DISSOLVE: 1,
    AnalysisOperation.OVERLAY_INTERSECTION: 2,
    AnalysisOperation.SPATIAL_JOIN: 2,
    AnalysisOperation.RESTORE_UNCOVERED_FEATURES: 2,
    AnalysisOperation.ATTRIBUTE_JOIN: 2,
    AnalysisOperation.VALIDATE_RESULT: 1,
    AnalysisOperation.EXPORT_GEOJSON: 1,
    AnalysisOperation.GENERATE_REPORT: 1,
}


def _validate_input_count(
    operation: AnalysisOperation,
    inputs: list[str],
) -> None:
    """Keep plan steps compatible with their future deterministic tools."""
    expected_count = _EXPECTED_INPUT_COUNTS.get(operation)
    if expected_count is not None and len(inputs) != expected_count:
        raise PlanSemanticError(
            PlanSemanticErrorCode.INVALID_OPERATION_PARAMETERS,
            f"Operation {operation.value!r} requires exactly "
            f"{expected_count} input(s), received {len(inputs)}.",
        )


def _validate_coverage_sequence(proposal: AnalysisPlanProposal) -> None:
    """Require the safe order for plans that estimate area coverage."""
    operations = [step.operation for step in proposal.steps]
    if AnalysisOperation.CALCULATE_COVERAGE_METRICS not in operations:
        return

    required_sequence = [
        AnalysisOperation.BUFFER,
        AnalysisOperation.DISSOLVE,
        AnalysisOperation.OVERLAY_INTERSECTION,
        AnalysisOperation.CALCULATE_COVERAGE_METRICS,
    ]
    search_from = 0
    for operation in required_sequence:
        try:
            position = operations.index(operation, search_from)
        except ValueError as error:
            raise PlanSemanticError(
                PlanSemanticErrorCode.INVALID_COVERAGE_SEQUENCE,
                "Coverage metrics require this ordered sequence: buffer, "
                "dissolve, overlay_intersection, "
                "calculate_coverage_metrics.",
            ) from error
        search_from = position + 1


def _validate_coverage_area_lineage(proposal: AnalysisPlanProposal) -> None:
    """Require the denominator area field to exist before overlay clipping."""
    for metric_index, metric_step in enumerate(proposal.steps):
        if metric_step.operation is not AnalysisOperation.CALCULATE_COVERAGE_METRICS:
            continue

        total_area_field = metric_step.parameters.get("total_area_field")
        overlay_positions = [
            index
            for index, step in enumerate(proposal.steps[:metric_index])
            if step.operation is AnalysisOperation.OVERLAY_INTERSECTION
        ]
        if not overlay_positions:
            continue
        overlay_index = overlay_positions[-1]
        has_matching_area_step = any(
            step.operation is AnalysisOperation.CALCULATE_GEOMETRY_AREA
            and step.parameters.get("output_field") == total_area_field
            for step in proposal.steps[:overlay_index]
        )
        if not has_matching_area_step:
            raise PlanSemanticError(
                PlanSemanticErrorCode.MISSING_AREA_LINEAGE,
                "Coverage total_area_field must be created by a "
                "calculate_geometry_area step before overlay_intersection, "
                "using the same output_field name.",
            )


def _validate_uncovered_feature_restore(proposal: AnalysisPlanProposal) -> None:
    """Keep completely uncovered target polygons in the final result."""
    operations = [step.operation for step in proposal.steps]
    if AnalysisOperation.OVERLAY_INTERSECTION not in operations:
        return
    overlay_index = operations.index(AnalysisOperation.OVERLAY_INTERSECTION)
    complete_target_input = proposal.steps[overlay_index].inputs[0]
    for metrics_index, metrics_step in enumerate(proposal.steps):
        if metrics_step.operation is not AnalysisOperation.CALCULATE_COVERAGE_METRICS:
            continue

        restore_positions = [
            index
            for index, operation in enumerate(operations)
            if operation is AnalysisOperation.RESTORE_UNCOVERED_FEATURES
            and index > metrics_index
        ]
        if not restore_positions:
            raise PlanSemanticError(
                PlanSemanticErrorCode.MISSING_UNCOVERED_RESTORE,
                "Coverage metrics must be left-joined back to the complete "
                "target polygons with restore_uncovered_features so zero-coverage "
                "features are retained.",
            )

        restore_step = proposal.steps[restore_positions[0]]
        if restore_step.inputs[0] != complete_target_input:
            raise PlanSemanticError(
                PlanSemanticErrorCode.MISSING_UNCOVERED_RESTORE,
                "restore_uncovered_features must use the complete target polygon "
                f"input {complete_target_input!r} as its left input.",
            )
        required_zero_fields = {
            metrics_step.parameters.get("intersection_area_field"),
            metrics_step.parameters.get("coverage_ratio_field"),
            metrics_step.parameters.get("estimated_covered_population_field"),
        }
        required_zero_fields.discard(None)
        fill_defaults = restore_step.parameters.get("fill_defaults")
        if not isinstance(fill_defaults, dict):
            continue
        missing_or_nonzero = sorted(
            str(field)
            for field in required_zero_fields
            if field not in fill_defaults or fill_defaults[field] != 0
        )
        if missing_or_nonzero:
            raise PlanSemanticError(
                PlanSemanticErrorCode.MISSING_UNCOVERED_RESTORE,
                "restore_uncovered_features fill_defaults must set these "
                "coverage fields to 0: " + ", ".join(missing_or_nonzero) + ".",
            )


def _validate_coverage_result_join(proposal: AnalysisPlanProposal) -> None:
    """Require metric and facility-count outputs to be explicitly combined."""
    operations = [step.operation for step in proposal.steps]
    if (
        AnalysisOperation.CALCULATE_COVERAGE_METRICS not in operations
        or AnalysisOperation.SPATIAL_JOIN not in operations
    ):
        return

    metrics_index = operations.index(AnalysisOperation.CALCULATE_COVERAGE_METRICS)
    spatial_join_index = operations.index(AnalysisOperation.SPATIAL_JOIN)
    restore_positions = [
        index
        for index, operation in enumerate(operations)
        if operation is AnalysisOperation.RESTORE_UNCOVERED_FEATURES
        and index > metrics_index
    ]
    restore_index = restore_positions[0] if restore_positions else metrics_index
    search_from = max(restore_index, spatial_join_index) + 1
    try:
        result_join_index = operations.index(
            AnalysisOperation.ATTRIBUTE_JOIN,
            search_from,
        )
    except ValueError as error:
        raise PlanSemanticError(
            PlanSemanticErrorCode.MISSING_RESULT_JOIN,
            "Coverage metrics and spatial-join counts must be combined by an "
            "attribute_join step before validation or export.",
        ) from error

    later_validation_positions = [
        index
        for index, operation in enumerate(operations)
        if operation is AnalysisOperation.VALIDATE_RESULT
    ]
    if later_validation_positions and result_join_index > later_validation_positions[0]:
        raise PlanSemanticError(
            PlanSemanticErrorCode.MISSING_RESULT_JOIN,
            "attribute_join must occur before validate_result.",
        )


def validate_analysis_plan(
    proposal: AnalysisPlanProposal,
) -> AnalysisPlanProposal:
    """Reject unsafe operation parameters and incomplete coverage methods."""
    errors: list[tuple[int | None, PlanSemanticError]] = []
    for step in proposal.steps:
        try:
            _validate_input_count(step.operation, step.inputs)
        except PlanSemanticError as error:
            errors.append((step.step_id, error))
        validator = _OPERATION_VALIDATORS.get(step.operation)
        if validator is not None:
            try:
                validator(step.parameters)
            except PlanSemanticError as error:
                errors.append((step.step_id, error))
    try:
        _validate_coverage_sequence(proposal)
    except PlanSemanticError as error:
        errors.append((None, error))
    try:
        _validate_coverage_area_lineage(proposal)
    except PlanSemanticError as error:
        errors.append((None, error))
    try:
        _validate_uncovered_feature_restore(proposal)
    except PlanSemanticError as error:
        errors.append((None, error))
    try:
        _validate_coverage_result_join(proposal)
    except PlanSemanticError as error:
        errors.append((None, error))

    if errors:
        first_error = errors[0][1]
        details = "\n".join(
            f"- {'Plan' if step_id is None else f'Step {step_id}'}: {error}"
            for step_id, error in errors
        )
        raise PlanSemanticError(
            first_error.code,
            f"Plan semantic validation failed:\n{details}",
        )
    return proposal

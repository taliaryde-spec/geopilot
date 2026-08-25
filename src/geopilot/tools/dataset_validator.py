"""Validate inspected datasets before spatial analysis."""

from geopilot.models import (
    DatasetProfile,
    DatasetValidationResult,
    ValidationIssue,
    ValidationIssueCode,
    ValidationSeverity,
)


class DatasetValidationError(ValueError):
    """Raised when a dataset is unsafe for spatial analysis."""

    def __init__(self, result: DatasetValidationResult) -> None:
        """Keep structured issues while providing a readable exception."""
        self.result = result
        details = "; ".join(
            f"{issue.code.value}: {issue.message}"
            for issue in result.issues
            if issue.severity is ValidationSeverity.ERROR
        )
        super().__init__(f"Dataset validation failed: {details}")


def validate_dataset_profile(profile: DatasetProfile) -> DatasetValidationResult:
    """Return structured validation issues for an inspected dataset."""
    issues: list[ValidationIssue] = []

    if profile.feature_count == 0:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.EMPTY_DATASET,
                severity=ValidationSeverity.ERROR,
                message="Dataset contains no features.",
                remediation="Provide a dataset containing at least one feature.",
            )
        )

    if profile.crs is None:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.MISSING_CRS,
                severity=ValidationSeverity.ERROR,
                message="Dataset has no coordinate reference system.",
                remediation="Define the source CRS before spatial analysis.",
            )
        )

    missing_geometry_count = profile.missing_values.get(
        profile.geometry_column,
        0,
    )
    if missing_geometry_count > 0:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.MISSING_GEOMETRY,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Dataset contains {missing_geometry_count} missing geometries."
                ),
                field=profile.geometry_column,
                count=missing_geometry_count,
                remediation="Remove affected rows or provide valid geometries.",
            )
        )

    if profile.invalid_geometry_count > 0:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.INVALID_GEOMETRY,
                severity=ValidationSeverity.ERROR,
                message=(
                    "Dataset contains "
                    f"{profile.invalid_geometry_count} invalid geometries."
                ),
                field=profile.geometry_column,
                count=profile.invalid_geometry_count,
                remediation="Repair invalid geometries before spatial analysis.",
            )
        )

    if profile.empty_geometry_count > 0:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.EMPTY_GEOMETRY,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Dataset contains {profile.empty_geometry_count} empty geometries."
                ),
                field=profile.geometry_column,
                count=profile.empty_geometry_count,
                remediation="Remove empty geometries or replace them with valid ones.",
            )
        )

    missing_attribute_count = sum(
        count
        for field, count in profile.missing_values.items()
        if field != profile.geometry_column
    )
    if missing_attribute_count > 0:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.MISSING_ATTRIBUTE_VALUES,
                severity=ValidationSeverity.WARNING,
                message=(
                    "Dataset contains "
                    f"{missing_attribute_count} missing attribute values."
                ),
                count=missing_attribute_count,
                remediation=(
                    "Review missing attributes and disclose or fill them when needed."
                ),
            )
        )

    return DatasetValidationResult(source=profile.source, issues=issues)


def ensure_dataset_is_analysis_ready(
    profile: DatasetProfile,
) -> DatasetValidationResult:
    """Return validation results or raise when analysis must stop."""
    result = validate_dataset_profile(profile)
    if not result.can_proceed:
        raise DatasetValidationError(result)
    return result

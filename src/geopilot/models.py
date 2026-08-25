"""Structured data models returned by GeoPilot tools."""

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class DatasetProfile(BaseModel):
    """Validated summary of a vector geospatial dataset."""

    source: str = Field(description="Original dataset path")
    feature_count: int = Field(ge=0, description="Number of features")
    columns: list[str] = Field(description="Dataset column names")
    geometry_column: str = Field(description="Active geometry column name")
    geometry_types: dict[str, int] = Field(description="Geometry type counts")
    crs: str | None = Field(description="Coordinate reference system")
    bounds: tuple[float, float, float, float] | None = Field(
        description="Bounds ordered as min_x, min_y, max_x, max_y"
    )
    missing_values: dict[str, int] = Field(description="Missing values per column")
    invalid_geometry_count: int = Field(
        ge=0,
        description="Number of invalid non-null geometries",
    )
    empty_geometry_count: int = Field(
        ge=0,
        description="Number of empty geometries",
    )


class ValidationSeverity(StrEnum):
    """Whether an issue blocks analysis or only needs disclosure."""

    ERROR = "error"
    WARNING = "warning"


class ValidationIssueCode(StrEnum):
    """Stable identifiers used by application and Agent logic."""

    EMPTY_DATASET = "empty_dataset"
    MISSING_CRS = "missing_crs"
    MISSING_GEOMETRY = "missing_geometry"
    INVALID_GEOMETRY = "invalid_geometry"
    EMPTY_GEOMETRY = "empty_geometry"
    MISSING_ATTRIBUTE_VALUES = "missing_attribute_values"


class ValidationIssue(BaseModel):
    """A machine-readable problem discovered during dataset validation."""

    code: ValidationIssueCode
    severity: ValidationSeverity
    message: str = Field(min_length=1, description="Human-readable explanation")
    field: str | None = Field(default=None, description="Related dataset field")
    count: int | None = Field(default=None, ge=0, description="Affected item count")
    remediation: str | None = Field(
        default=None,
        description="Suggested action that can resolve the issue",
    )


class DatasetValidationResult(BaseModel):
    """Structured decision about whether a dataset is safe to analyze."""

    source: str = Field(description="Dataset path copied from its profile")
    issues: list[ValidationIssue] = Field(default_factory=list)

    @computed_field
    @property
    def can_proceed(self) -> bool:
        """Return whether validation found no blocking errors."""
        return all(
            issue.severity is not ValidationSeverity.ERROR for issue in self.issues
        )


class DatasetIntakeResult(BaseModel):
    """Combined inspection and validation output for one dataset."""

    profile: DatasetProfile
    validation: DatasetValidationResult

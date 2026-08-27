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


class MetricCrsRecommendationMethod(StrEnum):
    """How GeoPilot selected a CRS suitable for metric analysis."""

    EXISTING_METRIC_CRS = "existing_metric_crs"
    ESTIMATED_UTM_CRS = "estimated_utm_crs"


class MetricCrsRecommendation(BaseModel):
    """Deterministic recommendation for distance and buffer operations."""

    source: str = Field(description="Original dataset path")
    source_crs: str = Field(description="CRS declared by the input dataset")
    recommended_crs: str = Field(
        description="Projected CRS recommended for metric analysis"
    )
    recommended_epsg: int | None = Field(
        description="EPSG code when the recommended CRS has one"
    )
    linear_unit: str = Field(description="Linear unit of the recommended CRS")
    requires_reprojection: bool = Field(
        description="Whether data must be reprojected before metric analysis"
    )
    method: MetricCrsRecommendationMethod
    warnings: list[str] = Field(default_factory=list)


class ReprojectionResult(BaseModel):
    """Metadata for one persisted, reprojected vector dataset."""

    source: str
    output: str
    feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    source_crs: str
    target_crs: str


class GeometryAreaResult(BaseModel):
    """Metadata and summary statistics for a persisted area calculation."""

    source: str
    output: str
    feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    output_field: str
    minimum_area_m2: float = Field(ge=0)
    maximum_area_m2: float = Field(ge=0)
    total_area_m2: float = Field(ge=0)


class BufferResult(BaseModel):
    """Metadata for field-driven metric buffer geometries."""

    source: str
    output: str
    feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    distance_field: str
    minimum_distance_m: float = Field(gt=0)
    maximum_distance_m: float = Field(gt=0)
    quadrant_segments: int = Field(ge=1)


class DissolveResult(BaseModel):
    """Metadata for a unioned polygon coverage artifact."""

    source: str
    output: str
    input_feature_count: int = Field(ge=1)
    feature_count: int = Field(ge=1)
    geometry_types: dict[str, int]
    crs: str
    method: str


class OverlayIntersectionResult(BaseModel):
    """Metadata for a persisted polygon intersection artifact."""

    left_source: str
    right_source: str
    output: str
    left_feature_count: int = Field(ge=1)
    right_feature_count: int = Field(ge=1)
    feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    how: str


class CoverageMetricsResult(BaseModel):
    """Metadata for per-target coverage metrics."""

    source: str
    output: str
    feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    key_field: str
    intersection_area_field: str
    total_area_field: str
    coverage_ratio_field: str
    population_field: str
    estimated_covered_population_field: str
    population_method: str
    total_covered_area_m2: float = Field(ge=0)


class RestoreUncoveredResult(BaseModel):
    """Metadata for restoring target polygons omitted by an intersection."""

    target_source: str
    metrics_source: str
    output: str
    feature_count: int = Field(ge=0)
    restored_feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    key_field: str
    fill_defaults: dict[str, float]


class SpatialJoinCountResult(BaseModel):
    """Metadata for per-target spatial relationship counts."""

    left_source: str
    right_source: str
    output: str
    feature_count: int = Field(ge=0)
    relationship_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    key_field: str
    output_field: str
    predicate: str


class AttributeJoinResult(BaseModel):
    """Metadata for a left attribute join that preserves target geometry."""

    left_source: str
    right_source: str
    output: str
    feature_count: int = Field(ge=0)
    matched_feature_count: int = Field(ge=0)
    unmatched_feature_count: int = Field(ge=0)
    geometry_types: dict[str, int]
    crs: str
    left_key: str
    right_key: str

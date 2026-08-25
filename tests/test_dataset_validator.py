"""Tests for dataset validation rules."""

import pytest

from geopilot.models import (
    DatasetProfile,
    ValidationIssueCode,
    ValidationSeverity,
)
from geopilot.tools.dataset_validator import (
    DatasetValidationError,
    ensure_dataset_is_analysis_ready,
    validate_dataset_profile,
)


def make_profile() -> DatasetProfile:
    """Return a valid profile that individual tests can modify."""
    return DatasetProfile(
        source="facilities.geojson",
        feature_count=2,
        columns=["name", "geometry"],
        geometry_column="geometry",
        geometry_types={"Point": 2},
        crs="EPSG:4326",
        bounds=(121.47, 31.23, 121.48, 31.24),
        missing_values={"name": 0, "geometry": 0},
        invalid_geometry_count=0,
        empty_geometry_count=0,
    )


def test_validate_dataset_profile_accepts_valid_dataset() -> None:
    result = validate_dataset_profile(make_profile())

    assert result.source == "facilities.geojson"
    assert result.can_proceed is True
    assert result.issues == []
    assert result.model_dump()["can_proceed"] is True


def test_validate_dataset_profile_reports_blocking_issues() -> None:
    profile = make_profile().model_copy(
        update={
            "feature_count": 4,
            "crs": None,
            "missing_values": {"name": 0, "geometry": 1},
            "invalid_geometry_count": 2,
            "empty_geometry_count": 1,
        }
    )

    result = validate_dataset_profile(profile)

    assert result.can_proceed is False
    assert [issue.code for issue in result.issues] == [
        ValidationIssueCode.MISSING_CRS,
        ValidationIssueCode.MISSING_GEOMETRY,
        ValidationIssueCode.INVALID_GEOMETRY,
        ValidationIssueCode.EMPTY_GEOMETRY,
    ]
    assert all(issue.severity is ValidationSeverity.ERROR for issue in result.issues)
    assert [issue.count for issue in result.issues] == [None, 1, 2, 1]


def test_validate_dataset_profile_rejects_empty_dataset() -> None:
    profile = make_profile().model_copy(
        update={
            "feature_count": 0,
            "geometry_types": {},
            "bounds": None,
        }
    )

    result = validate_dataset_profile(profile)

    assert result.can_proceed is False
    assert [issue.code for issue in result.issues] == [
        ValidationIssueCode.EMPTY_DATASET
    ]


def test_validate_dataset_profile_warns_about_missing_attributes() -> None:
    profile = make_profile().model_copy(
        update={"missing_values": {"name": 1, "geometry": 0}}
    )

    result = ensure_dataset_is_analysis_ready(profile)

    assert result.can_proceed is True
    assert len(result.issues) == 1
    assert result.issues[0].code is ValidationIssueCode.MISSING_ATTRIBUTE_VALUES
    assert result.issues[0].severity is ValidationSeverity.WARNING
    assert result.issues[0].count == 1


def test_ensure_dataset_is_analysis_ready_raises_for_errors() -> None:
    profile = make_profile().model_copy(update={"crs": None})

    with pytest.raises(DatasetValidationError, match="missing_crs") as error_info:
        ensure_dataset_is_analysis_ready(profile)

    assert error_info.value.result.can_proceed is False

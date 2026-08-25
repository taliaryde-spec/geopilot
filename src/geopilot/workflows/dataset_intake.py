"""Inspect and validate a dataset as one reusable workflow."""

from pathlib import Path

from geopilot.models import DatasetIntakeResult
from geopilot.tools.dataset_inspector import inspect_vector_dataset
from geopilot.tools.dataset_validator import validate_dataset_profile


def inspect_and_validate_dataset(source: str | Path) -> DatasetIntakeResult:
    """Return inspection facts and a decision about analysis readiness."""
    profile = inspect_vector_dataset(source)
    validation = validate_dataset_profile(profile)
    return DatasetIntakeResult(profile=profile, validation=validation)

"""Inspect and validate a dataset as one reusable workflow."""

from pathlib import Path

from geopilot.models import DatasetIntakeResult
from geopilot.tools.dataset_inspector import inspect_geodataframe
from geopilot.tools.dataset_loader import load_geospatial_dataset
from geopilot.tools.dataset_validator import validate_dataset_profile


def inspect_and_validate_dataset(
    source: str | Path,
    *,
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
) -> DatasetIntakeResult:
    """Return inspection facts and a decision about analysis readiness."""
    source_path = Path(source)
    frame = load_geospatial_dataset(
        source_path,
        longitude_column=longitude_column,
        latitude_column=latitude_column,
    )
    profile = inspect_geodataframe(frame, source_path)

    validation = validate_dataset_profile(profile)
    return DatasetIntakeResult(profile=profile, validation=validation)

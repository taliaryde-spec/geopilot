"""Inspect vector geospatial datasets."""

from pathlib import Path
from typing import cast

import geopandas as gpd

from geopilot.models import DatasetProfile


def inspect_vector_dataset(source: str | Path) -> DatasetProfile:
    """Return a validated summary of a vector geospatial dataset."""
    source_path = Path(source).resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"Dataset does not exist: {source_path}")

    frame = gpd.read_file(source_path)
    return inspect_geodataframe(frame, source_path)


def inspect_geodataframe(
    frame: gpd.GeoDataFrame,
    source: str | Path,
) -> DatasetProfile:
    """Return a validated summary of an in-memory geospatial dataset."""
    source_path = Path(source).resolve()

    geometry = frame.geometry
    non_null_geometry = cast(
        gpd.GeoSeries,
        geometry[~geometry.isna()],
    )
    non_empty_geometry = cast(
        gpd.GeoSeries,
        non_null_geometry[~non_null_geometry.is_empty],
    )

    geometry_counts = non_null_geometry.geom_type.value_counts().sort_index()
    geometry_types = {
        str(geometry_type): int(count)
        for geometry_type, count in geometry_counts.items()
    }

    if non_empty_geometry.empty:
        bounds = None
    else:
        min_x, min_y, max_x, max_y = non_empty_geometry.total_bounds
        bounds = (
            float(min_x),
            float(min_y),
            float(max_x),
            float(max_y),
        )

    missing_values = {
        str(column): int(count) for column, count in frame.isna().sum().items()
    }

    crs = frame.crs.to_string() if frame.crs is not None else None

    return DatasetProfile(
        source=str(source_path),
        feature_count=len(frame),
        columns=[str(column) for column in frame.columns],
        geometry_column=str(frame.geometry.name),
        geometry_types=geometry_types,
        crs=crs,
        bounds=bounds,
        missing_values=missing_values,
        invalid_geometry_count=int((~non_null_geometry.is_valid).sum()),
        empty_geometry_count=int(non_null_geometry.is_empty.sum()),
    )

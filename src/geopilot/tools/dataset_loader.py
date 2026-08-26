"""Load supported geospatial datasets into a common in-memory representation."""

from pathlib import Path

import geopandas as gpd

from geopilot.tools.csv_point_loader import load_csv_points


def load_geospatial_dataset(
    source: str | Path,
    *,
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
) -> gpd.GeoDataFrame:
    """Load a coordinate CSV or vector dataset as a GeoDataFrame."""
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Dataset does not exist: {source_path}")

    if source_path.suffix.lower() == ".csv":
        return load_csv_points(
            source_path,
            longitude_column=longitude_column,
            latitude_column=latitude_column,
        )
    return gpd.read_file(source_path)

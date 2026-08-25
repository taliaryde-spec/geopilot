"""Load longitude and latitude columns from CSV as point geometries."""

from enum import StrEnum
from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd


class CsvPointErrorCode(StrEnum):
    """Stable identifiers for CSV coordinate input errors."""

    CSV_READ_ERROR = "csv_read_error"
    COORDINATE_COLUMNS_NOT_DISTINCT = "coordinate_columns_not_distinct"
    MISSING_COORDINATE_COLUMNS = "missing_coordinate_columns"
    MISSING_COORDINATES = "missing_coordinates"
    NON_NUMERIC_COORDINATES = "non_numeric_coordinates"
    LONGITUDE_OUT_OF_RANGE = "longitude_out_of_range"
    LATITUDE_OUT_OF_RANGE = "latitude_out_of_range"
    GEOMETRY_COLUMN_CONFLICT = "geometry_column_conflict"


class CsvPointLoadError(ValueError):
    """Raised when CSV rows cannot be safely converted to points."""

    def __init__(
        self,
        code: CsvPointErrorCode,
        message: str,
        *,
        field: str | None = None,
        count: int | None = None,
        row_numbers: list[int] | None = None,
    ) -> None:
        """Store a stable code alongside a human-readable explanation."""
        self.code = code
        self.field = field
        self.count = count
        self.row_numbers = row_numbers or []
        super().__init__(message)


def _csv_row_numbers(mask: list[bool]) -> list[int]:
    """Convert a boolean row mask to one-based CSV line numbers."""
    return [index + 2 for index, is_invalid in enumerate(mask) if is_invalid]


def load_csv_points(
    source: str | Path,
    *,
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
) -> gpd.GeoDataFrame:
    """Load a CSV and create EPSG:4326 point geometries from coordinates."""
    source_path = Path(source).resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"Dataset does not exist: {source_path}")

    if longitude_column == latitude_column:
        raise CsvPointLoadError(
            CsvPointErrorCode.COORDINATE_COLUMNS_NOT_DISTINCT,
            "Longitude and latitude columns must be different.",
        )

    try:
        frame = pd.read_csv(source_path)
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
    ) as error:
        raise CsvPointLoadError(
            CsvPointErrorCode.CSV_READ_ERROR,
            f"CSV could not be read: {error}",
        ) from error

    if "geometry" in frame.columns:
        raise CsvPointLoadError(
            CsvPointErrorCode.GEOMETRY_COLUMN_CONFLICT,
            "CSV already contains a reserved geometry column.",
            field="geometry",
        )
    required_columns = [longitude_column, latitude_column]
    missing_columns = [
        column for column in required_columns if column not in frame.columns
    ]
    if missing_columns:
        names = ", ".join(missing_columns)
        raise CsvPointLoadError(
            CsvPointErrorCode.MISSING_COORDINATE_COLUMNS,
            f"CSV is missing coordinate columns: {names}.",
        )

    coordinate_values = cast(pd.DataFrame, frame.loc[:, required_columns])
    coordinate_values = cast(
        pd.DataFrame,
        coordinate_values.replace(r"^\s*$", pd.NA, regex=True),
    )
    missing_coordinate_mask = coordinate_values.isna().to_numpy().any(axis=1)
    missing_coordinate_count = int(missing_coordinate_mask.sum())
    if missing_coordinate_count > 0:
        raise CsvPointLoadError(
            CsvPointErrorCode.MISSING_COORDINATES,
            f"CSV contains {missing_coordinate_count} rows with missing coordinates.",
            count=missing_coordinate_count,
            row_numbers=_csv_row_numbers(
                cast(list[bool], missing_coordinate_mask.tolist())
            ),
        )

    longitude = cast(
        pd.Series,
        pd.to_numeric(coordinate_values[longitude_column], errors="coerce"),
    )
    latitude = cast(
        pd.Series,
        pd.to_numeric(coordinate_values[latitude_column], errors="coerce"),
    )
    non_numeric_mask = longitude.isna().to_numpy() | latitude.isna().to_numpy()
    non_numeric_count = int(non_numeric_mask.sum())
    if non_numeric_count > 0:
        raise CsvPointLoadError(
            CsvPointErrorCode.NON_NUMERIC_COORDINATES,
            f"CSV contains {non_numeric_count} rows with non-numeric coordinates.",
            count=non_numeric_count,
            row_numbers=_csv_row_numbers(cast(list[bool], non_numeric_mask.tolist())),
        )

    longitude_values = longitude.to_numpy(dtype=float)
    latitude_values = latitude.to_numpy(dtype=float)

    invalid_longitude_mask = (longitude_values < -180) | (longitude_values > 180)
    invalid_longitude_count = int(invalid_longitude_mask.sum())
    if invalid_longitude_count > 0:
        raise CsvPointLoadError(
            CsvPointErrorCode.LONGITUDE_OUT_OF_RANGE,
            f"CSV contains {invalid_longitude_count} longitudes outside [-180, 180].",
            field=longitude_column,
            count=invalid_longitude_count,
            row_numbers=_csv_row_numbers(
                cast(list[bool], invalid_longitude_mask.tolist())
            ),
        )

    invalid_latitude_mask = (latitude_values < -90) | (latitude_values > 90)
    invalid_latitude_count = int(invalid_latitude_mask.sum())
    if invalid_latitude_count > 0:
        raise CsvPointLoadError(
            CsvPointErrorCode.LATITUDE_OUT_OF_RANGE,
            f"CSV contains {invalid_latitude_count} latitudes outside [-90, 90].",
            field=latitude_column,
            count=invalid_latitude_count,
            row_numbers=_csv_row_numbers(
                cast(list[bool], invalid_latitude_mask.tolist())
            ),
        )

    result = frame.copy()
    result[longitude_column] = longitude_values
    result[latitude_column] = latitude_values
    return gpd.GeoDataFrame(
        result,
        geometry=gpd.points_from_xy(longitude_values, latitude_values),
        crs="EPSG:4326",
    )

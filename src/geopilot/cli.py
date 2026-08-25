"""Command-line interface for GeoPilot."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from geopilot.tools.csv_point_loader import CsvPointLoadError
from geopilot.workflows.dataset_intake import inspect_and_validate_dataset

EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 3
EXIT_VALIDATION_ERROR = 4
EXIT_INPUT_ERROR = 5


def build_parser() -> argparse.ArgumentParser:
    """Build the GeoPilot command-line parser."""
    parser = argparse.ArgumentParser(
        prog="geopilot",
        description="Inspect and analyze geospatial datasets with GeoPilot.",
    )
    subparsers = parser.add_subparsers(dest="command")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect and validate a vector dataset or coordinate CSV.",
    )
    inspect_parser.add_argument(
        "source",
        type=Path,
        help="Path to GeoJSON, Shapefile, or a coordinate CSV.",
    )
    inspect_parser.add_argument(
        "--longitude-column",
        default="longitude",
        help="CSV longitude column name (default: longitude).",
    )
    inspect_parser.add_argument(
        "--latitude-column",
        default="latitude",
        help="CSV latitude column name (default: latitude).",
    )
    return parser


def _run_inspect(
    source: Path,
    *,
    longitude_column: str,
    latitude_column: str,
) -> int:
    """Run dataset intake and print a structured JSON result."""
    try:
        result = inspect_and_validate_dataset(
            source,
            longitude_column=longitude_column,
            latitude_column=latitude_column,
        )
    except FileNotFoundError as error:
        payload = {
            "error": {
                "code": "dataset_not_found",
                "message": str(error),
            }
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_FILE_NOT_FOUND
    except CsvPointLoadError as error:
        error_payload: dict[str, object] = {
            "code": error.code.value,
            "message": str(error),
        }
        if error.field is not None:
            error_payload["field"] = error.field
        if error.count is not None:
            error_payload["count"] = error.count
        if error.row_numbers:
            error_payload["row_numbers"] = error.row_numbers

        payload = {"error": error_payload}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_INPUT_ERROR

    print(result.model_dump_json(indent=2))
    if result.validation.can_proceed:
        return EXIT_SUCCESS
    return EXIT_VALIDATION_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    """Run the GeoPilot command-line entry point."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "inspect":
        return _run_inspect(
            arguments.source,
            longitude_column=arguments.longitude_column,
            latitude_column=arguments.latitude_column,
        )

    parser.print_help()
    return EXIT_SUCCESS

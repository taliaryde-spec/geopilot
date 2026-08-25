"""Command-line interface for GeoPilot."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from geopilot.workflows.dataset_intake import inspect_and_validate_dataset

EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 3
EXIT_VALIDATION_ERROR = 4


def build_parser() -> argparse.ArgumentParser:
    """Build the GeoPilot command-line parser."""
    parser = argparse.ArgumentParser(
        prog="geopilot",
        description="Inspect and analyze geospatial datasets with GeoPilot.",
    )
    subparsers = parser.add_subparsers(dest="command")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect and validate a vector dataset.",
    )
    inspect_parser.add_argument(
        "source",
        type=Path,
        help="Path to a vector dataset such as GeoJSON or Shapefile.",
    )
    return parser


def _run_inspect(source: Path) -> int:
    """Run dataset intake and print a structured JSON result."""
    try:
        result = inspect_and_validate_dataset(source)
    except FileNotFoundError as error:
        payload = {
            "error": {
                "code": "dataset_not_found",
                "message": str(error),
            }
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_FILE_NOT_FOUND

    print(result.model_dump_json(indent=2))
    if result.validation.can_proceed:
        return EXIT_SUCCESS
    return EXIT_VALIDATION_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    """Run the GeoPilot command-line entry point."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "inspect":
        return _run_inspect(arguments.source)

    parser.print_help()
    return EXIT_SUCCESS

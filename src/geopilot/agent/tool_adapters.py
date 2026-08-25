"""Adapters that expose deterministic GeoPilot workflows as Agent tools."""

from pydantic import BaseModel, Field

from geopilot.agent.registry import AgentTool, ToolRegistry
from geopilot.workflows.dataset_intake import inspect_and_validate_dataset


class InspectDatasetArguments(BaseModel):
    """Arguments accepted by the inspect_dataset Agent tool."""

    source: str = Field(description="Path to GeoJSON, Shapefile, or CSV")
    longitude_column: str = Field(
        default="longitude",
        description="Longitude column used for CSV input",
    )
    latitude_column: str = Field(
        default="latitude",
        description="Latitude column used for CSV input",
    )


def _inspect_dataset(arguments: BaseModel) -> BaseModel:
    """Validate tool arguments and run the dataset intake workflow."""
    parameters = InspectDatasetArguments.model_validate(arguments)
    return inspect_and_validate_dataset(
        parameters.source,
        longitude_column=parameters.longitude_column,
        latitude_column=parameters.latitude_column,
    )


def build_default_tool_registry() -> ToolRegistry:
    """Return the tools currently available to the GeoPilot Agent."""
    registry = ToolRegistry()
    registry.register(
        AgentTool(
            name="inspect_dataset",
            description=(
                "Inspect and validate a GeoJSON, Shapefile, or coordinate CSV. "
                "Use this before making claims or planning spatial analysis."
            ),
            input_model=InspectDatasetArguments,
            handler=_inspect_dataset,
            recoverable_errors=(OSError, ValueError),
        )
    )
    return registry

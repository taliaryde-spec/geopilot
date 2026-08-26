"""Adapters that expose deterministic GeoPilot workflows as Agent tools."""

from pydantic import BaseModel, Field

from geopilot.agent.registry import AgentTool, ToolRegistry
from geopilot.tools.crs_recommender import recommend_metric_crs
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


class RecommendMetricCrsArguments(BaseModel):
    """Arguments accepted by the recommend_metric_crs Agent tool."""

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


def _recommend_metric_crs(arguments: BaseModel) -> BaseModel:
    """Validate tool arguments and determine a metric analysis CRS."""
    parameters = RecommendMetricCrsArguments.model_validate(arguments)
    return recommend_metric_crs(
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
    registry.register(
        AgentTool(
            name="recommend_metric_crs",
            description=(
                "Deterministically recommend a metre-based projected CRS for "
                "buffer, distance, or area analysis. Use this before naming a "
                "target EPSG code or planning metric spatial operations."
            ),
            input_model=RecommendMetricCrsArguments,
            handler=_recommend_metric_crs,
            recoverable_errors=(OSError, ValueError),
        )
    )
    return registry

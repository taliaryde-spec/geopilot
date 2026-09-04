"""Prompt catalog for controlled comparisons instead of silent rewrites."""

from geopilot.agent.prompting.models import PromptSpec, PromptVariant
from geopilot.agent.prompting.templates import GEOPILOT_SYSTEM_PROMPT, PROMPT_VERSION

MINIMAL_SYSTEM_PROMPT = """
You are GeoPilot, a geospatial analysis Agent. Use available tools to ground
claims about local datasets and GIS methods. Never invent fields, CRS values,
counts, geometries, or analysis results. Use a metric CRS for distance, buffer,
or area work. Submit a structured analysis plan before any operation that would
transform data or write analysis outputs; a submitted plan must wait for human
approval. If a tool fails, explain the failure and do not pretend it succeeded.
""".strip()

FEW_SHOT_APPENDIX = """

Decision examples:
- If asked only to inspect a dataset, call inspect_dataset and stop after
  reporting evidence; do not submit a plan.
- If asked why EPSG:4326 is unsuitable for metre buffers and search_knowledge
  is available, retrieve project evidence before answering; do not invent a
  target EPSG code.
- If a requested dataset is missing, report the tool error and stop instead of
  switching to another file.
- If asked to transform, buffer, join, export, or report, inspect every source,
  obtain a tool-computed metric CRS when needed, then submit a complete plan and
  state that it is awaiting approval. Do not execute it.
""".rstrip()


PROMPT_CATALOG: dict[PromptVariant, PromptSpec] = {
    PromptVariant.MINIMAL: PromptSpec(
        variant=PromptVariant.MINIMAL,
        version="1.0.0",
        description="Short safety baseline without detailed workflow rules.",
        system_prompt=MINIMAL_SYSTEM_PROMPT,
    ),
    PromptVariant.STRUCTURED: PromptSpec(
        variant=PromptVariant.STRUCTURED,
        version=PROMPT_VERSION,
        description="Current production-like rules with explicit GIS contracts.",
        system_prompt=GEOPILOT_SYSTEM_PROMPT,
    ),
    PromptVariant.STRUCTURED_FEW_SHOT: PromptSpec(
        variant=PromptVariant.STRUCTURED_FEW_SHOT,
        version=f"{PROMPT_VERSION}-fs1",
        description="Structured rules plus four concise decision examples.",
        system_prompt=GEOPILOT_SYSTEM_PROMPT + FEW_SHOT_APPENDIX,
        includes_few_shot=True,
    ),
}

DEFAULT_PROMPT_VARIANT = PromptVariant.STRUCTURED


def get_prompt_spec(variant: PromptVariant | str) -> PromptSpec:
    """Return one catalog entry as an immutable copy."""
    selected = PromptVariant(variant)
    return PROMPT_CATALOG[selected].model_copy(deep=True)


def list_prompt_specs() -> list[PromptSpec]:
    """Return prompt candidates in stable experiment order."""
    return [get_prompt_spec(variant) for variant in PromptVariant]

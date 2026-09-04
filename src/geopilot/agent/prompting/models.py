"""Validated metadata for comparable GeoPilot system prompts."""

from enum import StrEnum

from pydantic import BaseModel, Field


class PromptVariant(StrEnum):
    """Controlled system-prompt variants used by the experiment."""

    MINIMAL = "minimal"
    STRUCTURED = "structured"
    STRUCTURED_FEW_SHOT = "structured_few_shot"


class PromptSpec(BaseModel):
    """One immutable prompt candidate with auditable experiment metadata."""

    variant: PromptVariant
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    includes_few_shot: bool = False

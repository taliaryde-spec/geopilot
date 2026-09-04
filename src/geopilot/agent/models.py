"""Provider-neutral data contracts used by the GeoPilot Agent."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelUsage(BaseModel):
    """Provider-neutral token usage reported for one or more model turns."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)

    def plus(self, other: "ModelUsage") -> "ModelUsage":
        """Add usage without mutating either source record."""
        return ModelUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cached_input_tokens=(self.cached_input_tokens + other.cached_input_tokens),
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


class ToolDefinition(BaseModel):
    """Description and JSON Schema presented to a language model."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """A model request to invoke one registered tool."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    """One provider-neutral message in the Agent working memory."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ModelResponse(BaseModel):
    """Normalized response returned by any language-model adapter."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: ModelUsage | None = None


class ToolResult(BaseModel):
    """Structured result returned to the model after a tool call."""

    tool_call_id: str
    name: str
    success: bool
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error: str | None = None


class AgentRunResult(BaseModel):
    """Final answer plus the complete auditable execution trace."""

    final_answer: str
    messages: list[AgentMessage]
    tool_results: list[ToolResult]
    model_turns: int = Field(ge=1)
    usage: ModelUsage | None = None
    usage_reported_turns: int = Field(default=0, ge=0)

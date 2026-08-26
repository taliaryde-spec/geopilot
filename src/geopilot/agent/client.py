"""Language-model interface implemented by provider adapters."""

from collections.abc import Sequence
from typing import Protocol

from geopilot.agent.models import AgentMessage, ModelResponse, ToolDefinition


class ModelRequestError(RuntimeError):
    """Raised when a model request fails before a valid response is returned."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ModelResponseError(RuntimeError):
    """Raised when a provider returns an invalid tool call or response."""


class ChatModel(Protocol):
    """Minimal interface required by the provider-neutral Agent loop."""

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        """Return text, tool calls, or both for the next Agent turn."""
        ...

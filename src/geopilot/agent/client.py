"""Language-model interface implemented by provider adapters."""

from collections.abc import Sequence
from typing import Protocol

from geopilot.agent.models import AgentMessage, ModelResponse, ToolDefinition


class ChatModel(Protocol):
    """Minimal interface required by the provider-neutral Agent loop."""

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        """Return text, tool calls, or both for the next Agent turn."""
        ...

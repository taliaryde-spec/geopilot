"""Provider-neutral Agent loop with tool execution and working memory."""

from geopilot.agent.client import ChatModel
from geopilot.agent.models import (
    AgentMessage,
    AgentRunResult,
    ToolResult,
)
from geopilot.agent.prompts import GEOPILOT_SYSTEM_PROMPT
from geopilot.agent.registry import ToolRegistry


class AgentProtocolError(RuntimeError):
    """Raised when a model returns neither text nor tool calls."""


class AgentMaxTurnsError(RuntimeError):
    """Raised when the Agent cannot finish within its safety limit."""


class AgentRunner:
    """Run model decisions and deterministic tools until a final answer exists."""

    def __init__(
        self,
        model: ChatModel,
        tools: ToolRegistry,
        *,
        system_prompt: str = GEOPILOT_SYSTEM_PROMPT,
        max_model_turns: int = 6,
    ) -> None:
        if max_model_turns < 1:
            raise ValueError("max_model_turns must be at least 1")
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_model_turns = max_model_turns

    def run(self, user_input: str) -> AgentRunResult:
        """Execute one user task with in-run working memory."""
        if not user_input.strip():
            raise ValueError("user_input must not be empty")

        messages = [
            AgentMessage(role="system", content=self._system_prompt),
            AgentMessage(role="user", content=user_input),
        ]
        tool_results: list[ToolResult] = []
        tool_definitions = self._tools.definitions()

        for model_turn in range(1, self._max_model_turns + 1):
            response = self._model.complete(messages, tool_definitions)
            messages.append(
                AgentMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_result = self._tools.execute(tool_call)
                    tool_results.append(tool_result)
                    messages.append(
                        AgentMessage(
                            role="tool",
                            name=tool_call.name,
                            tool_call_id=tool_call.id,
                            content=tool_result.model_dump_json(),
                        )
                    )
                continue

            if response.content is not None and response.content.strip():
                return AgentRunResult(
                    final_answer=response.content,
                    messages=messages,
                    tool_results=tool_results,
                    model_turns=model_turn,
                )

            raise AgentProtocolError(
                "Model returned neither a final answer nor a tool call."
            )

        raise AgentMaxTurnsError(
            f"Agent exceeded the limit of {self._max_model_turns} model turns."
        )

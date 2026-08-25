"""Tool registration, schema discovery, validation, and execution."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ValidationError

from geopilot.agent.models import ToolCall, ToolDefinition, ToolResult

ToolHandler = Callable[[BaseModel], BaseModel]


@dataclass(frozen=True, slots=True)
class AgentTool:
    """A validated application function exposed to the language model."""

    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    recoverable_errors: tuple[type[Exception], ...] = ()

    def definition(self) -> ToolDefinition:
        """Return the provider-neutral definition shown to the model."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )

    def invoke(self, arguments: dict[str, object]) -> BaseModel:
        """Validate model arguments before invoking application code."""
        validated_arguments = self.input_model.model_validate(arguments)
        return self.handler(validated_arguments)


def _execution_error_code(error: Exception) -> str:
    """Preserve a stable domain error code when an exception provides one."""
    code = getattr(error, "code", None)
    if isinstance(code, Enum):
        return str(code.value)
    if isinstance(code, str):
        return code
    return "tool_execution_error"


class ToolRegistry:
    """Registry used by both model discovery and runtime execution."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """Register one uniquely named tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool is already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[ToolDefinition]:
        """Return all tool schemas in deterministic registration order."""
        return [tool.definition() for tool in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute one call without allowing tool failures to crash the Agent."""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=False,
                error_code="unknown_tool",
                error=f"Tool is not registered: {call.name}",
            )

        try:
            output = tool.invoke(call.arguments)
        except ValidationError as error:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=False,
                error_code="invalid_tool_arguments",
                error=str(error),
            )
        except tool.recoverable_errors as error:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=False,
                error_code=_execution_error_code(error),
                error=str(error),
            )

        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=True,
            output=output.model_dump(mode="json"),
        )

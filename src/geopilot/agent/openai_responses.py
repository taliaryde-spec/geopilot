"""OpenAI Responses API adapter for the provider-neutral Agent runtime."""

import json
from collections.abc import Sequence
from typing import Any, Protocol, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)
from openai.types.responses import (
    EasyInputMessageParam,
    FunctionToolParam,
    ResponseFunctionToolCall,
)
from openai.types.responses.response_input_param import (
    FunctionCallOutput,
    ResponseInputItemParam,
    ResponseInputParam,
)

from geopilot.agent.client import ModelRequestError, ModelResponseError
from geopilot.agent.config import ModelConfigurationError, ModelSettings
from geopilot.agent.models import (
    AgentMessage,
    ModelResponse,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any:
        """Create one model response."""
        ...


class _OpenAIClient(Protocol):
    @property
    def responses(self) -> _ResponsesResource:
        """Return the Responses API resource."""
        ...


class OpenAIResponsesModel:
    """Translate GeoPilot messages and tools to the OpenAI Responses API."""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        client: _OpenAIClient | None = None,
    ) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
            return

        try:
            self._client = cast(
                _OpenAIClient,
                OpenAI(
                    api_key=settings.api_key.get_secret_value(),
                    base_url=settings.base_url,
                    timeout=settings.timeout_seconds,
                    max_retries=settings.max_retries,
                ),
            )
        except (ImportError, OpenAIError, ValueError) as error:
            raise ModelConfigurationError(
                f"Could not initialize the OpenAI client: {error}"
            ) from error

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        """Request the next text response or function call from the model."""
        instructions, input_items = _build_input(messages)
        function_tools = [_build_function_tool(tool) for tool in tools]

        try:
            response = self._client.responses.create(
                model=self._settings.model,
                instructions=instructions,
                input=input_items,
                tools=function_tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_output_tokens=self._settings.max_output_tokens,
                store=False,
            )
        except AuthenticationError as error:
            raise ModelRequestError(
                "model_authentication_error",
                "Model authentication failed. Check OPENAI_API_KEY.",
            ) from error
        except RateLimitError as error:
            raise ModelRequestError(
                "model_rate_limit",
                "The model provider rejected the request because of a rate or quota limit.",
            ) from error
        except APITimeoutError as error:
            raise ModelRequestError(
                "model_timeout",
                "The model request timed out.",
            ) from error
        except APIConnectionError as error:
            raise ModelRequestError(
                "model_connection_error",
                "Could not connect to the model provider.",
            ) from error
        except APIStatusError as error:
            raise ModelRequestError(
                "model_api_error",
                f"The model provider returned HTTP {error.status_code}.",
            ) from error
        except OpenAIError as error:
            raise ModelRequestError(
                "model_request_error",
                "The model request failed.",
            ) from error

        return _normalize_response(response)


def _build_input(
    messages: Sequence[AgentMessage],
) -> tuple[str | None, ResponseInputParam]:
    """Convert provider-neutral working memory to Responses API input items."""
    instructions = (
        "\n\n".join(
            message.content
            for message in messages
            if message.role == "system" and message.content
        )
        or None
    )
    input_items: list[ResponseInputItemParam] = []

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "user" or message.role == "assistant":
            if message.content:
                input_message: EasyInputMessageParam = {
                    "type": "message",
                    "role": message.role,
                    "content": message.content,
                }
                input_items.append(input_message)
            if message.role == "assistant":
                input_items.extend(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": json.dumps(
                            tool_call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                    for tool_call in message.tool_calls
                )
            continue
        if message.role == "tool":
            if message.tool_call_id is None:
                raise ModelResponseError(
                    "Tool messages must include the originating tool_call_id."
                )
            tool_output: FunctionCallOutput = {
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": message.content or "",
            }
            if message.name is not None:
                tool_output["name"] = message.name
            input_items.append(tool_output)

    return instructions, input_items


def _build_function_tool(tool: ToolDefinition) -> FunctionToolParam:
    """Convert one GeoPilot tool definition to an OpenAI function tool."""
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": cast(dict[str, object], tool.input_schema),
        "strict": False,
    }


def _normalize_response(response: Any) -> ModelResponse:
    """Normalize OpenAI output text and function calls for the Agent loop."""
    tool_calls: list[ToolCall] = []
    for item in response.output:
        if not isinstance(item, ResponseFunctionToolCall):
            continue
        try:
            arguments = json.loads(item.arguments)
        except json.JSONDecodeError as error:
            raise ModelResponseError(
                f"Tool {item.name!r} returned invalid JSON arguments."
            ) from error
        if not isinstance(arguments, dict):
            raise ModelResponseError(
                f"Tool {item.name!r} arguments must be a JSON object."
            )
        tool_calls.append(
            ToolCall(
                id=item.call_id,
                name=item.name,
                arguments=arguments,
            )
        )

    content = response.output_text.strip() or None
    return ModelResponse(
        content=content,
        tool_calls=tool_calls,
        usage=_normalize_usage(response),
    )


def _normalize_usage(response: Any) -> ModelUsage | None:
    """Normalize optional Responses API token details."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return ModelUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        cached_input_tokens=int(getattr(input_details, "cached_tokens", 0) or 0),
        reasoning_tokens=int(getattr(output_details, "reasoning_tokens", 0) or 0),
    )

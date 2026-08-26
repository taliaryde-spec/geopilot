"""OpenAI-compatible Chat Completions adapter for external providers."""

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
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)

from geopilot.agent.client import ModelRequestError, ModelResponseError
from geopilot.agent.config import ModelConfigurationError, ModelSettings
from geopilot.agent.models import (
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
)


class _ChatCompletionsResource(Protocol):
    def create(self, **kwargs: Any) -> Any:
        """Create one chat completion."""
        ...


class _ChatResource(Protocol):
    @property
    def completions(self) -> _ChatCompletionsResource:
        """Return the Chat Completions resource."""
        ...


class _OpenAICompatibleClient(Protocol):
    @property
    def chat(self) -> _ChatResource:
        """Return the Chat API resource."""
        ...


class OpenAICompatibleChatModel:
    """Use one Agent loop with DeepSeek, OpenRouter, and compatible APIs."""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        client: _OpenAICompatibleClient | None = None,
    ) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
            return

        try:
            self._client = cast(
                _OpenAICompatibleClient,
                OpenAI(
                    api_key=settings.api_key.get_secret_value(),
                    base_url=settings.base_url,
                    timeout=settings.timeout_seconds,
                    max_retries=settings.max_retries,
                ),
            )
        except (ImportError, OpenAIError, ValueError) as error:
            raise ModelConfigurationError(
                f"Could not initialize the {settings.provider.value} client: {error}"
            ) from error

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        """Request the next text response or function call from the provider."""
        chat_messages = [_build_message(message) for message in messages]
        function_tools = [_build_function_tool(tool) for tool in tools]

        try:
            response = self._client.chat.completions.create(
                model=self._settings.model,
                messages=chat_messages,
                tools=function_tools,
                tool_choice="auto",
                max_tokens=self._settings.max_output_tokens,
            )
        except AuthenticationError as error:
            raise ModelRequestError(
                "model_authentication_error",
                f"{self._settings.provider.value} authentication failed. Check its API key.",
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
                f"Could not connect to {self._settings.provider.value}.",
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

        if not response.choices:
            raise ModelResponseError("The model provider returned no choices.")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ModelResponseError(
                f"{self._settings.provider.value} stopped after reaching "
                f"max_tokens={self._settings.max_output_tokens}; the response "
                "or tool arguments may be truncated. Increase "
                "GEOPILOT_MODEL_MAX_OUTPUT_TOKENS or use "
                "--max-output-tokens, then retry."
            )
        if choice.finish_reason == "content_filter":
            raise ModelResponseError(
                "The model provider stopped because of its content filter."
            )
        if choice.finish_reason == "insufficient_system_resource":
            raise ModelResponseError(
                "The model provider stopped because inference resources were "
                "temporarily insufficient. Retry the request."
            )

        message = choice.message
        tool_calls = [
            _normalize_tool_call(tool_call)
            for tool_call in message.tool_calls or []
            if isinstance(tool_call, ChatCompletionMessageFunctionToolCall)
        ]
        content = message.content.strip() if message.content else None
        return ModelResponse(content=content or None, tool_calls=tool_calls)


def _build_message(message: AgentMessage) -> ChatCompletionMessageParam:
    """Convert one provider-neutral message to Chat Completions format."""
    if message.role == "system":
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": message.content or "",
        }
        return system_message
    if message.role == "user":
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": message.content or "",
        }
        return user_message
    if message.role == "assistant":
        assistant_tool_calls: list[ChatCompletionMessageFunctionToolCallParam] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(
                        tool_call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
            for tool_call in message.tool_calls
        ]
        assistant_message: ChatCompletionAssistantMessageParam = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": assistant_tool_calls,
        }
        return assistant_message
    if message.tool_call_id is None:
        raise ModelResponseError(
            "Tool messages must include the originating tool_call_id."
        )
    tool_message: ChatCompletionToolMessageParam = {
        "role": "tool",
        "tool_call_id": message.tool_call_id,
        "content": message.content or "",
    }
    return tool_message


def _build_function_tool(
    tool: ToolDefinition,
) -> ChatCompletionFunctionToolParam:
    """Convert a GeoPilot tool definition to Chat Completions format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": False,
        },
    }


def _normalize_tool_call(
    tool_call: ChatCompletionMessageFunctionToolCall,
) -> ToolCall:
    """Validate JSON arguments before the deterministic tool registry sees them."""
    try:
        arguments = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as error:
        raise ModelResponseError(
            f"Tool {tool_call.function.name!r} returned invalid JSON arguments "
            f"at line {error.lineno}, column {error.colno} "
            f"(argument length: {len(tool_call.function.arguments)} characters)."
        ) from error
    if not isinstance(arguments, dict):
        raise ModelResponseError(
            f"Tool {tool_call.function.name!r} arguments must be a JSON object."
        )
    return ToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments=arguments,
    )

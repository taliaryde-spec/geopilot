"""Tests for DeepSeek/OpenRouter-compatible Chat Completions translation."""

import json
from dataclasses import dataclass
from typing import Any

import pytest
from openai.types.chat import ChatCompletionMessageFunctionToolCall
from openai.types.chat.chat_completion_message_function_tool_call import Function
from pydantic import SecretStr

from geopilot.agent.chat_completions import OpenAICompatibleChatModel
from geopilot.agent.client import ModelResponseError
from geopilot.agent.config import ModelProvider, ModelSettings
from geopilot.agent.models import AgentMessage, ToolCall, ToolDefinition


@dataclass
class FakeMessage:
    content: str | None
    tool_calls: list[ChatCompletionMessageFunctionToolCall] | None = None


@dataclass
class FakeChoice:
    message: FakeMessage
    finish_reason: str = "stop"


@dataclass
class FakeChatCompletion:
    choices: list[FakeChoice]


class FakeCompletionsResource:
    def __init__(self, responses: list[FakeChatCompletion]) -> None:
        self._responses = responses.copy()
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeChatCompletion:
        self.requests.append(kwargs)
        return self._responses.pop(0)


class FakeChatResource:
    def __init__(self, responses: list[FakeChatCompletion]) -> None:
        self.completions = FakeCompletionsResource(responses)


class FakeClient:
    def __init__(self, responses: list[FakeChatCompletion]) -> None:
        self.chat = FakeChatResource(responses)


def _settings(
    provider: ModelProvider = ModelProvider.DEEPSEEK,
) -> ModelSettings:
    base_url = (
        "https://api.deepseek.com"
        if provider == ModelProvider.DEEPSEEK
        else "https://openrouter.ai/api/v1"
    )
    return ModelSettings(
        provider=provider,
        api_key=SecretStr("test-key"),
        model="test-model",
        base_url=base_url,
    )


def _response_with_tool_call(
    arguments: str = '{"source":"data.geojson"}',
    *,
    finish_reason: str = "tool_calls",
) -> FakeChatCompletion:
    return FakeChatCompletion(
        choices=[
            FakeChoice(
                message=FakeMessage(
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageFunctionToolCall(
                            id="call-1",
                            type="function",
                            function=Function(
                                name="inspect_dataset",
                                arguments=arguments,
                            ),
                        )
                    ],
                ),
                finish_reason=finish_reason,
            )
        ]
    )


def test_adapter_translates_tool_schema_and_normalizes_call() -> None:
    client = FakeClient([_response_with_tool_call()])
    model = OpenAICompatibleChatModel(_settings(), client=client)
    tool = ToolDefinition(
        name="inspect_dataset",
        description="Inspect a geospatial dataset.",
        input_schema={
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
    )

    response = model.complete(
        [
            AgentMessage(role="system", content="Use GIS tools."),
            AgentMessage(role="user", content="Inspect data.geojson"),
        ],
        [tool],
    )

    request = client.chat.completions.requests[0]
    assert request["model"] == "test-model"
    assert request["messages"] == [
        {"role": "system", "content": "Use GIS tools."},
        {"role": "user", "content": "Inspect data.geojson"},
    ]
    assert request["tools"][0]["function"]["name"] == "inspect_dataset"
    assert request["tool_choice"] == "auto"
    assert response.tool_calls == [
        ToolCall(
            id="call-1",
            name="inspect_dataset",
            arguments={"source": "data.geojson"},
        )
    ]


def test_adapter_returns_assistant_call_and_tool_result_to_provider() -> None:
    final_response = FakeChatCompletion(
        choices=[FakeChoice(message=FakeMessage(content="检查完成。"))]
    )
    client = FakeClient([final_response])
    model = OpenAICompatibleChatModel(
        _settings(ModelProvider.OPENROUTER),
        client=client,
    )

    response = model.complete(
        [
            AgentMessage(role="system", content="Use tools."),
            AgentMessage(role="user", content="Inspect data.geojson"),
            AgentMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="inspect_dataset",
                        arguments={"source": "data.geojson"},
                    )
                ],
            ),
            AgentMessage(
                role="tool",
                name="inspect_dataset",
                tool_call_id="call-1",
                content=json.dumps({"success": True}),
            ),
        ],
        [],
    )

    request_messages = client.chat.completions.requests[0]["messages"]
    assert request_messages[2]["tool_calls"][0]["id"] == "call-1"
    assert request_messages[3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"success": true}',
    }
    assert response.content == "检查完成。"


def test_adapter_rejects_invalid_tool_arguments() -> None:
    client = FakeClient([_response_with_tool_call("not-json")])
    model = OpenAICompatibleChatModel(_settings(), client=client)

    with pytest.raises(
        ModelResponseError,
        match=r"invalid JSON arguments at line 1, column 1.*8 characters",
    ):
        model.complete([AgentMessage(role="user", content="Inspect data")], [])


def test_adapter_reports_truncated_tool_arguments() -> None:
    client = FakeClient(
        [
            _response_with_tool_call(
                '{"user_goal":"unfinished',
                finish_reason="length",
            )
        ]
    )
    model = OpenAICompatibleChatModel(_settings(), client=client)

    with pytest.raises(
        ModelResponseError,
        match=r"max_tokens=4096.*may be truncated",
    ):
        model.complete([AgentMessage(role="user", content="Create a plan")], [])

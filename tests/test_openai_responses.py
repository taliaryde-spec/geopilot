"""Tests for configuration and OpenAI Responses API translation."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from openai.types.responses import ResponseFunctionToolCall
from pydantic import SecretStr

from geopilot.agent.config import (
    ModelConfigurationError,
    ModelProvider,
    ModelSettings,
)
from geopilot.agent.models import AgentMessage, ToolCall, ToolDefinition
from geopilot.agent.openai_responses import (
    ModelResponseError,
    OpenAIResponsesModel,
)


@dataclass
class FakeResponse:
    output_text: str
    output: list[ResponseFunctionToolCall]


class FakeResponsesResource:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses.copy()
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.requests.append(kwargs)
        return self._responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = FakeResponsesResource(responses)


def _settings() -> ModelSettings:
    return ModelSettings(
        provider=ModelProvider.OPENAI,
        api_key=SecretStr("test-key"),
        model="test-model",
    )


def _tool_call(arguments: str = '{"source":"data.geojson"}') -> FakeResponse:
    return FakeResponse(
        output_text="",
        output=[
            ResponseFunctionToolCall(
                type="function_call",
                call_id="call-1",
                name="inspect_dataset",
                arguments=arguments,
            )
        ],
    )


def test_settings_load_environment_without_exposing_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEOPILOT_PROVIDER=openai\n"
        "OPENAI_API_KEY=secret-value\n"
        "GEOPILOT_MODEL=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GEOPILOT_PROVIDER", raising=False)
    monkeypatch.delenv("GEOPILOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEOPILOT_MODEL", raising=False)

    settings = ModelSettings.from_environment(env_file=env_file)

    assert settings.model == "test-model"
    assert settings.api_key.get_secret_value() == "secret-value"
    assert "secret-value" not in repr(settings)


def test_settings_report_missing_required_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEOPILOT_PROVIDER", raising=False)
    monkeypatch.delenv("GEOPILOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEOPILOT_MODEL", raising=False)

    with pytest.raises(ModelConfigurationError, match="OPENAI_API_KEY"):
        ModelSettings.from_environment(env_file=tmp_path / "missing.env")


def test_settings_apply_deepseek_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEOPILOT_PROVIDER=deepseek\nDEEPSEEK_API_KEY=secret-value\n",
        encoding="utf-8",
    )
    for variable in (
        "GEOPILOT_PROVIDER",
        "GEOPILOT_API_KEY",
        "GEOPILOT_MODEL",
        "GEOPILOT_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "GEOPILOT_MODEL_MAX_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = ModelSettings.from_environment(env_file=env_file)

    assert settings.provider == ModelProvider.DEEPSEEK
    assert settings.model == "deepseek-v4-flash"
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.max_output_tokens == 4096
    assert os.getenv("DEEPSEEK_API_KEY") is None
    assert os.getenv("GEOPILOT_MODEL_MAX_OUTPUT_TOKENS") is None


def test_settings_allow_cli_output_token_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEOPILOT_PROVIDER=deepseek\n"
        "DEEPSEEK_API_KEY=secret-value\n"
        "GEOPILOT_MODEL_MAX_OUTPUT_TOKENS=1200\n",
        encoding="utf-8",
    )
    for variable in (
        "GEOPILOT_PROVIDER",
        "GEOPILOT_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEOPILOT_MODEL_MAX_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = ModelSettings.from_environment(
        env_file=env_file,
        max_output_tokens=4096,
    )

    assert settings.max_output_tokens == 4096


def test_settings_require_openrouter_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEOPILOT_PROVIDER=openrouter\nOPENROUTER_API_KEY=secret-value\n",
        encoding="utf-8",
    )
    for variable in (
        "GEOPILOT_PROVIDER",
        "GEOPILOT_API_KEY",
        "GEOPILOT_MODEL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ModelConfigurationError, match="OPENROUTER_MODEL"):
        ModelSettings.from_environment(env_file=env_file)


def test_adapter_translates_tools_and_normalizes_function_call() -> None:
    client = FakeOpenAIClient([_tool_call()])
    model = OpenAIResponsesModel(_settings(), client=client)
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

    request = client.responses.requests[0]
    assert request["model"] == "test-model"
    assert request["instructions"] == "Use GIS tools."
    assert request["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": "Inspect data.geojson",
        }
    ]
    assert request["tools"][0]["name"] == "inspect_dataset"
    assert request["parallel_tool_calls"] is False
    assert request["store"] is False
    assert response.tool_calls == [
        ToolCall(
            id="call-1",
            name="inspect_dataset",
            arguments={"source": "data.geojson"},
        )
    ]


def test_adapter_returns_function_result_to_model() -> None:
    client = FakeOpenAIClient([FakeResponse(output_text="检查完成。", output=[])])
    model = OpenAIResponsesModel(_settings(), client=client)

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

    request_items = client.responses.requests[0]["input"]
    assert request_items[1]["type"] == "function_call"
    assert request_items[2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": '{"success": true}',
        "name": "inspect_dataset",
    }
    assert response.content == "检查完成。"


def test_adapter_rejects_invalid_function_arguments() -> None:
    client = FakeOpenAIClient([_tool_call("not-json")])
    model = OpenAIResponsesModel(_settings(), client=client)

    with pytest.raises(ModelResponseError, match="invalid JSON"):
        model.complete([AgentMessage(role="user", content="Inspect data")], [])

"""Core Agent runtime for GeoPilot."""

from geopilot.agent.chat_completions import OpenAICompatibleChatModel
from geopilot.agent.client import ModelRequestError, ModelResponseError
from geopilot.agent.config import (
    ModelConfigurationError,
    ModelProvider,
    ModelSettings,
)
from geopilot.agent.factory import build_model
from geopilot.agent.openai_responses import OpenAIResponsesModel
from geopilot.agent.prompting import PromptSpec, PromptVariant, get_prompt_spec
from geopilot.agent.runner import (
    AgentMaxTurnsError,
    AgentProtocolError,
    AgentRunner,
)

__all__ = [
    "AgentMaxTurnsError",
    "AgentProtocolError",
    "AgentRunner",
    "ModelConfigurationError",
    "ModelProvider",
    "ModelRequestError",
    "ModelResponseError",
    "ModelSettings",
    "OpenAICompatibleChatModel",
    "OpenAIResponsesModel",
    "PromptSpec",
    "PromptVariant",
    "build_model",
    "get_prompt_spec",
]

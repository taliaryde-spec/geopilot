"""Construct language-model adapters without coupling them to the CLI."""

from geopilot.agent.chat_completions import OpenAICompatibleChatModel
from geopilot.agent.client import ChatModel
from geopilot.agent.config import ModelProvider, ModelSettings
from geopilot.agent.openai_responses import OpenAIResponsesModel


def build_model(settings: ModelSettings) -> ChatModel:
    """Select the provider adapter while preserving one Agent runtime."""
    if settings.provider == ModelProvider.OPENAI:
        return OpenAIResponsesModel(settings)
    return OpenAICompatibleChatModel(settings)

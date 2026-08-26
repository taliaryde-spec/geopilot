"""Environment-backed configuration for language-model providers."""

import os
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr


class ModelConfigurationError(ValueError):
    """Raised when required model configuration is missing or invalid."""


class ModelProvider(StrEnum):
    """Language-model providers supported by the GeoPilot CLI."""

    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"


_PROVIDER_KEY_VARIABLES = {
    ModelProvider.OPENAI: "OPENAI_API_KEY",
    ModelProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
    ModelProvider.OPENROUTER: "OPENROUTER_API_KEY",
}

_PROVIDER_DEFAULT_MODELS = {
    ModelProvider.OPENAI: "gpt-5-mini",
    ModelProvider.DEEPSEEK: "deepseek-v4-flash",
    ModelProvider.OPENROUTER: None,
}

_PROVIDER_BASE_URLS = {
    ModelProvider.OPENAI: None,
    ModelProvider.DEEPSEEK: "https://api.deepseek.com",
    ModelProvider.OPENROUTER: "https://openrouter.ai/api/v1",
}


class ModelSettings(BaseModel):
    """Validated provider, credentials, model, and request safety limits."""

    provider: ModelProvider
    api_key: SecretStr
    model: str = Field(min_length=1)
    base_url: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_output_tokens: int = Field(default=4096, ge=64, le=20_000)

    @classmethod
    def from_environment(
        cls,
        *,
        provider: str | ModelProvider | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_output_tokens: int | None = None,
        env_file: Path | None = None,
    ) -> "ModelSettings":
        """Read a local .env file without mutating the process environment."""
        dotenv_path = env_file if env_file is not None else Path.cwd() / ".env"
        file_values = dotenv_values(dotenv_path=dotenv_path)

        def config_value(name: str, default: str | None = None) -> str | None:
            """Return an environment override, then .env value, then default."""
            environment_value = os.getenv(name)
            if environment_value is not None:
                return environment_value
            file_value = file_values.get(name)
            return file_value if file_value is not None else default

        provider_name = str(
            provider or config_value("GEOPILOT_PROVIDER", ModelProvider.OPENAI.value)
        ).lower()
        try:
            selected_provider = ModelProvider(provider_name)
        except ValueError as error:
            supported = ", ".join(item.value for item in ModelProvider)
            raise ModelConfigurationError(
                f"Unsupported model provider {provider_name!r}. Choose one of: {supported}."
            ) from error

        provider_key_variable = _PROVIDER_KEY_VARIABLES[selected_provider]
        api_key = (config_value("GEOPILOT_API_KEY", "") or "").strip() or (
            config_value(provider_key_variable, "") or ""
        ).strip()
        provider_model_variable = f"{selected_provider.value.upper()}_MODEL"
        model_name = (
            model
            or config_value("GEOPILOT_MODEL", "")
            or config_value(provider_model_variable, "")
            or _PROVIDER_DEFAULT_MODELS[selected_provider]
            or ""
        ).strip()
        configured_base_url = (
            base_url
            or config_value("GEOPILOT_BASE_URL")
            or _PROVIDER_BASE_URLS[selected_provider]
        )
        if configured_base_url is not None:
            configured_base_url = configured_base_url.strip() or None

        missing_variables = []
        if not api_key:
            missing_variables.append(f"{provider_key_variable} (or GEOPILOT_API_KEY)")
        if not model_name:
            missing_variables.append(f"{provider_model_variable} (or GEOPILOT_MODEL)")
        if missing_variables:
            joined_names = ", ".join(missing_variables)
            raise ModelConfigurationError(
                f"Missing model configuration: {joined_names}. "
                "Set the variables in .env or the current terminal."
            )

        try:
            return cls.model_validate(
                {
                    "provider": selected_provider,
                    "api_key": api_key,
                    "model": model_name,
                    "base_url": configured_base_url,
                    "timeout_seconds": config_value(
                        "GEOPILOT_MODEL_TIMEOUT_SECONDS",
                        "30",
                    ),
                    "max_retries": config_value(
                        "GEOPILOT_MODEL_MAX_RETRIES",
                        "2",
                    ),
                    "max_output_tokens": (
                        max_output_tokens
                        if max_output_tokens is not None
                        else config_value(
                            "GEOPILOT_MODEL_MAX_OUTPUT_TOKENS",
                            "4096",
                        )
                    ),
                }
            )
        except ValueError as error:
            raise ModelConfigurationError(
                f"Invalid model configuration: {error}"
            ) from error

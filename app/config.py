"""Конфигурация из переменных окружения / .env. Все переменные описаны в .env.example."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.kb.retriever import RetrieverMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    kb_path: Path = Path("data/kb")
    kb_retriever: RetrieverMode = "auto"

    llm_provider: Literal["fake", "anthropic"] = "fake"
    llm_model: str = "claude-opus-5-5"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_timeout_s: float = Field(default=15.0, gt=0.0)
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    anthropic_api_key: SecretStr | None = None

    amocrm_mode: Literal["mock", "live"] = "mock"
    amocrm_subdomain: str | None = None
    amocrm_access_token: SecretStr | None = None

    @model_validator(mode="after")
    def _check_required_secrets(self) -> Self:
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "LLM_PROVIDER=anthropic требует ANTHROPIC_API_KEY (или LLM_PROVIDER=fake)"
            )
        if self.amocrm_mode == "live" and not (self.amocrm_subdomain and self.amocrm_access_token):
            raise ValueError(
                "AMOCRM_MODE=live требует AMOCRM_SUBDOMAIN и AMOCRM_ACCESS_TOKEN "
                "(или AMOCRM_MODE=mock)"
            )
        return self

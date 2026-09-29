import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def test_defaults_work_without_any_secrets(settings: Settings) -> None:
    assert settings.llm_provider == "fake"
    assert settings.amocrm_mode == "mock"
    assert settings.anthropic_api_key is None


def test_anthropic_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(_env_file=None)


def test_amocrm_live_mode_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AMOCRM_SUBDOMAIN", raising=False)
    monkeypatch.delenv("AMOCRM_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("AMOCRM_MODE", "live")

    with pytest.raises(ValidationError, match="AMOCRM_SUBDOMAIN"):
        Settings(_env_file=None)


def test_amocrm_live_mode_requires_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AMOCRM_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("AMOCRM_MODE", "live")
    monkeypatch.setenv("AMOCRM_SUBDOMAIN", "example")
    monkeypatch.setenv("AMOCRM_ACCESS_TOKEN", "token")

    with pytest.raises(ValidationError, match="AMOCRM_WEBHOOK_SECRET"):
        Settings(_env_file=None)


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_are_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")

    assert "sk-ant-test-secret" not in repr(Settings(_env_file=None))


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.MULTILINE))

    missing = {name.upper() for name in Settings.model_fields} - documented

    assert not missing, f".env.example не описывает: {sorted(missing)}"

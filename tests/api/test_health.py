from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings
from app.main import create_app


def test_health_returns_ok_without_api_key(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "llm_provider": "fake"}


def test_health_reports_configured_provider(settings: Settings) -> None:
    settings = settings.model_copy(update={"llm_provider": "anthropic"})
    client = TestClient(create_app(settings))

    assert client.get("/health").json()["llm_provider"] == "anthropic"

"""Критерий M5: POST /webhooks/amocrm отвечает < 2 с даже при «медленном» LLM; идемпотентность;
ошибки не приводят к не-2xx (amoCRM отключает хук после 100 невалидных ответов за 2 часа)."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.core.pipeline import AssistService
from app.integrations.amocrm.processor import WebhookProcessor
from app.llm.fake import FakeLLM
from app.main import create_app
from tests.integrations.amocrm.helpers import fixture

FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings.model_copy(update={"amocrm_webhook_secret": SecretStr("s3cret")}))
    with TestClient(app) as c:
        yield c


def drain(client: TestClient) -> None:
    """Дождаться фоновой обработки в цикле событий приложения."""
    processor: WebhookProcessor = client.app.state.amocrm  # type: ignore[attr-defined]
    assert client.portal is not None
    client.portal.call(processor.drain)


def post(client: TestClient, body: str, token: str = "s3cret") -> int:
    response = client.post(f"/webhooks/amocrm?token={token}", content=body, headers=FORM)
    return response.status_code


def test_webhook_responds_fast_even_if_llm_is_slow(client: TestClient) -> None:
    app = client.app
    state = app.state  # type: ignore[attr-defined]
    slow = AssistService(state.kb, state.retriever, FakeLLM(delay_s=3), timeout_s=15)
    state.amocrm._assist = slow  # подменяем LLM на «думающий» 3 секунды — дольше лимита amoCRM

    started = time.perf_counter()
    status = post(client, fixture("message_add_text_lead"))
    elapsed = time.perf_counter() - started

    assert status == 200
    assert elapsed < 2.0


def test_webhook_writes_mock_note_visible_in_demo(client: TestClient) -> None:
    assert post(client, fixture("message_add_text_lead")) == 200
    drain(client)

    feed = client.get("/v1/amocrm/notes").json()
    assert feed["mode"] == "mock"
    [note] = feed["notes"]
    assert note["target"] == {"entity": "leads", "id": 4242}
    assert note["text"].startswith("💡 Подсказка")


def test_repeated_delivery_creates_one_note(client: TestClient) -> None:
    body = fixture("message_add_text_lead")
    for _ in range(3):
        assert post(client, body) == 200
    drain(client)

    assert len(client.get("/v1/amocrm/notes").json()["notes"]) == 1


def test_outgoing_message_is_accepted_without_note(client: TestClient) -> None:
    assert post(client, fixture("outgoing_message_add_doc")) == 200
    drain(client)

    assert client.get("/v1/amocrm/notes").json()["notes"] == []


@pytest.mark.parametrize("body", ["", "garbage", "message%5Badd%5D%5B0%5D%5Btext%5D=no-id"])
def test_malformed_payload_still_gets_200(client: TestClient, body: str) -> None:
    assert post(client, body) == 200


def test_wrong_token_is_rejected(client: TestClient) -> None:
    assert post(client, fixture("message_add_text_lead"), token="wrong") == 401
    assert post(client, fixture("message_add_text_lead"), token="") == 401


def test_secret_is_optional_in_mock_mode(settings: Settings) -> None:
    with TestClient(create_app(settings)) as c:
        response = c.post(
            "/webhooks/amocrm", content=fixture("message_add_text_lead"), headers=FORM
        )

    assert response.status_code == 200

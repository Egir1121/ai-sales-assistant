"""Критерий M3: POST /v1/assist по контракту SPEC §4; сценарии S1, S4, S7 через HTTP."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_assist_service
from app.config import Settings
from app.core.pipeline import AssistService
from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from app.main import create_app

SPEC_REQUEST: dict[str, Any] = {
    "message": "Сколько стоит доставка в Казань и можно оплатить при получении?",
    "dialog": [
        {"role": "client", "text": "Здравствуйте, интересует ноутбук X15"},
        {
            "role": "manager",
            "text": "Добрый день! X15 в наличии, 89 990 ₽. Могу предложить сумку к нему",
        },
        {"role": "client", "text": "Сумка не нужна, спасибо"},
    ],
    "lead": {
        "id": 123,
        "stage": "Консультация",
        "client_name": "Анна",
        "product_ids": ["product.x15"],
    },
}

# Ключи из примера ответа в SPEC §4 — контракт, на который рассчитывает интеграция.
SPEC_KEYS = {
    "": {"request_id", "client_reply", "manager_hint", "meta"},
    "client_reply": {"text", "language", "kb_refs", "needs_manager"},
    "manager_hint": {
        "summary",
        "intent",
        "sentiment",
        "upsell",
        "upsell_suppressed_reason",
        "declined_offer_ids",
        "next_best_action",
        "risk_flags",
    },
    "upsell": {"offer_id", "title", "why", "pitch", "when_to_say", "confidence"},
    "meta": {
        "provider",
        "model",
        "prompt_version",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "fallback_used",
    },
}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def assist(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/v1/assist", json=body)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def test_response_matches_spec_contract(client: TestClient) -> None:
    data = assist(client, SPEC_REQUEST)

    assert SPEC_KEYS[""] <= data.keys()
    assert SPEC_KEYS["client_reply"] <= data["client_reply"].keys()
    assert SPEC_KEYS["manager_hint"] <= data["manager_hint"].keys()
    assert SPEC_KEYS["meta"] <= data["meta"].keys()
    assert data["manager_hint"]["upsell"], "в примере SPEC допродажа уместна"
    for offer in data["manager_hint"]["upsell"]:
        assert SPEC_KEYS["upsell"] <= offer.keys()


def test_s1_faq_answer_with_refs(client: TestClient) -> None:
    data = assist(client, SPEC_REQUEST)

    reply = data["client_reply"]
    assert reply["text"].startswith("Анна, здравствуйте!")
    assert {"faq.delivery_regions", "faq.payment"} <= set(reply["kb_refs"])
    assert "690 ₽" in reply["text"]
    assert reply["needs_manager"] is False
    assert data["meta"]["fallback_used"] is False


def test_s4_complaint_has_no_upsell(client: TestClient) -> None:
    data = assist(
        client,
        {
            "message": "Ноутбук X15 сломался через три дня, это ужас. Верните деньги!",
            "lead": {"product_ids": ["product.x15"]},
        },
    )

    hint = data["manager_hint"]
    assert hint["upsell"] == []
    assert hint["upsell_suppressed_reason"]
    assert hint["sentiment"] == "negative"
    assert data["client_reply"]["needs_manager"] is True


def test_s7_declined_offer_is_not_repeated(client: TestClient) -> None:
    body = dict(SPEC_REQUEST, message="А когда сможете доставить?")

    hint = assist(client, body)["manager_hint"]

    assert hint["declined_offer_ids"] == ["product.bag"]
    assert "product.bag" not in [o["offer_id"] for o in hint["upsell"]]
    assert hint["upsell"], "другие допродажи остаются"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": 42},
        {"message": "ok", "dialog": [{"role": "bot", "text": "hi"}]},
        {"message": "ok", "lead": {"product_ids": "product.x15"}},
    ],
)
def test_invalid_request_is_422(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/v1/assist", json=body).status_code == 422


def test_long_and_empty_messages_are_accepted(client: TestClient) -> None:
    assert assist(client, {"message": "доставка " * 600})["meta"]["fallback_used"] is False
    empty = assist(client, {"message": ""})
    assert empty["manager_hint"]["intent"] == "unclear"
    assert empty["manager_hint"]["upsell"] == []


def test_llm_failure_degrades_instead_of_500(client: TestClient) -> None:
    app = client.app
    kb, retriever = app.state.kb, app.state.retriever  # type: ignore[attr-defined]
    broken = AssistService(kb, retriever, FakeLLM(error=LLMError("down")), timeout_s=1)
    app.dependency_overrides[get_assist_service] = lambda: broken  # type: ignore[attr-defined]

    data = assist(client, SPEC_REQUEST)

    assert data["meta"]["fallback_used"] is True
    assert data["client_reply"]["text"] == kb.company.fallback_reply


def test_kb_products_endpoint(client: TestClient) -> None:
    response = client.get("/v1/kb/products")

    assert response.status_code == 200
    products = {p["id"]: p for p in response.json()}
    assert products["product.x15"] == {
        "id": "product.x15",
        "title": "Ноутбук X15",
        "price": 89990,
        "currency": "RUB",
        "tags": ["laptop"],
    }

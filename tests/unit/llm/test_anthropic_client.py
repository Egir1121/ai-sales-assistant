"""Anthropic-адаптер на подменённом HTTP-транспорте: форма запроса, разбор, ретрай, ошибки."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from anthropic import DefaultAsyncHttpxClient

from app.kb.models import KnowledgeBase
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import LLMError, LLMRequest
from app.llm.prompts import build_request
from app.llm.schema import LLMOutput
from tests.unit.llm.helpers import make_context

VALID_OUTPUT: dict[str, Any] = {
    "language": "ru",
    "intent": "delivery_payment_question",
    "sentiment": "neutral",
    "client_reply": "Доставка по России — 690 ₽.",
    "kb_refs": ["faq.delivery_regions"],
    "needs_manager": False,
    "summary": "Клиент уточняет доставку",
    "upsell": [],
    "declined_offer_ids": [],
    "next_best_action": "Уточнить адрес",
    "risk_flags": [],
}


def message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 300,
            "output_tokens": 120,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1500,
        },
    }


Handler = Callable[[httpx2.Request], httpx2.Response]


def client_with(handler: Handler, model: str = "claude-opus-5-5") -> AnthropicLLMClient:
    http = DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
    return AnthropicLLMClient(
        api_key="test-key",
        model=model,
        temperature=0.2,
        timeout_s=5,
        effort="low",
        http_client=http,
    )


@pytest.fixture
def request_(demo_kb: KnowledgeBase) -> LLMRequest:
    return build_request(make_context(demo_kb, "Сколько стоит доставка?"))


def replies(*bodies: dict[str, Any]) -> tuple[Handler, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    queue = list(bodies)

    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append({"headers": dict(req.headers), "body": json.loads(req.content)})
        return httpx2.Response(200, json=queue.pop(0))

    return handler, sent


async def test_request_shape(request_: LLMRequest) -> None:
    handler, sent = replies(message(json.dumps(VALID_OUTPUT)))

    result = await client_with(handler).generate(request_)

    body = sent[0]["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["system"][0]["text"] == request_.system
    content = body["messages"][0]["content"]
    assert content[0]["text"] == request_.kb_block
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1]["text"] == request_.dynamic_block
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in sent[0]["headers"]["anthropic-beta"]
    assert "temperature" not in body  # Opus 5.5 отклоняет sampling-параметры (допущение A8)

    assert result.output == LLMOutput.model_validate(VALID_OUTPUT)
    assert result.provider == "anthropic"
    assert result.tokens_in == 1800
    assert result.tokens_out == 120
    assert result.cost_usd is not None
    assert result.cost_usd > 0


async def test_temperature_sent_only_to_models_that_accept_it(request_: LLMRequest) -> None:
    handler, sent = replies(message(json.dumps(VALID_OUTPUT)))

    await client_with(handler, model="claude-haiku-4-5").generate(request_)

    body = sent[0]["body"]
    assert body["temperature"] == 0.2
    assert "effort" not in body.get("output_config", {})


async def test_invalid_json_is_retried_once(request_: LLMRequest) -> None:
    handler, sent = replies(message("не JSON"), message(json.dumps(VALID_OUTPUT)))

    result = await client_with(handler).generate(request_)

    assert len(sent) == 2
    assert result.output.intent == "delivery_payment_question"
    assert result.tokens_out == 240  # учитываем токены обеих попыток


async def test_invalid_twice_raises(request_: LLMRequest) -> None:
    bad = dict(VALID_OUTPUT, intent="nonsense")
    handler, sent = replies(message(json.dumps(bad)), message(json.dumps(bad)))

    with pytest.raises(LLMError, match="невалидный"):
        await client_with(handler).generate(request_)
    assert len(sent) == 2


async def test_refusal_is_an_error(request_: LLMRequest) -> None:
    handler, _ = replies(message("", stop_reason="refusal"))

    with pytest.raises(LLMError, match="refusal"):
        await client_with(handler).generate(request_)


async def test_http_error_is_wrapped_without_retry(request_: LLMRequest) -> None:
    calls = 0

    def handler(req: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}})

    with pytest.raises(LLMError):
        await client_with(handler).generate(request_)
    assert calls == 1  # ретраи SDK выключены: общий дедлайн контролирует пайплайн

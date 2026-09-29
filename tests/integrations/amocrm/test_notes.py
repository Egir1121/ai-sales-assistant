"""Запись примечания: mock не ходит в сеть, live — POST /api/v4/{leads|contacts}/{id}/notes."""

import json

import httpx2
import pytest

from app.core.models import AssistRequest
from app.core.pipeline import AssistService
from app.integrations.amocrm.formatting import format_note
from app.integrations.amocrm.models import NoteTarget
from app.integrations.amocrm.notes import AmoCRMError, LiveNotesClient, MockNotesClient
from app.kb.models import KnowledgeBase
from app.kb.retriever import make_retriever
from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from app.llm.prompts import PROMPT_VERSION


async def test_mock_client_keeps_notes_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    client = MockNotesClient()
    caplog.set_level("INFO", logger="app.integrations.amocrm")

    await client.add_note(NoteTarget(entity="leads", id=1), "💡 Подсказка")

    [note] = client.notes()
    assert note.target == NoteTarget(entity="leads", id=1)
    assert note.text == "💡 Подсказка"
    assert "leads/1" in caplog.text


async def test_mock_client_keeps_only_recent_notes() -> None:
    client = MockNotesClient(max_notes=3)
    for i in range(5):
        await client.add_note(NoteTarget(entity="leads", id=i), str(i))

    assert [n.text for n in client.notes()] == ["4", "3", "2"]  # свежие сверху


async def test_live_client_request_shape() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={"_embedded": {"notes": [{"id": 1, "entity_id": 4242}]}})

    client = LiveNotesClient(
        subdomain="example", access_token="secret-token", transport=httpx2.MockTransport(handler)
    )
    await client.add_note(NoteTarget(entity="leads", id=4242), "текст")
    await client.aclose()

    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == "https://example.amocrm.ru/api/v4/leads/4242/notes"
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert json.loads(request.content) == [{"note_type": "common", "params": {"text": "текст"}}]


async def test_live_client_raises_on_error_status() -> None:
    client = LiveNotesClient(
        subdomain="example",
        access_token="t",
        transport=httpx2.MockTransport(
            lambda r: httpx2.Response(401, json={"title": "Unauthorized"})
        ),
    )

    with pytest.raises(AmoCRMError, match="401"):
        await client.add_note(NoteTarget(entity="contacts", id=1), "x")


async def test_note_format(demo_kb: KnowledgeBase) -> None:
    service = AssistService(demo_kb, make_retriever(demo_kb), FakeLLM(), timeout_s=5)
    response = await service.assist(
        AssistRequest(message="Когда доставите X15?", lead={"product_ids": ["product.x15"]})  # type: ignore[arg-type]
    )

    note = format_note(response)

    assert note.startswith("💡 Подсказка")
    assert note.index("💡 Подсказка") < note.index("✉️ Черновик ответа")
    assert response.client_reply.text in note
    assert response.manager_hint.upsell[0].title in note
    assert response.manager_hint.upsell[0].pitch in note
    assert f"prompt {PROMPT_VERSION}" in note
    assert response.request_id in note
    assert note.rstrip().splitlines()[-1].endswith(response.request_id)


async def test_note_marks_fallback(demo_kb: KnowledgeBase) -> None:
    service = AssistService(demo_kb, make_retriever(demo_kb), FakeLLM(error=LLMError("x")), 5)

    note = format_note(await service.assist(AssistRequest(message="Доставка?")))

    assert "LLM недоступен" in note

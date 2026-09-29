"""Обработка вебхуков: история по talk_id, идемпотентность, вложения, куда пишется примечание."""

import logging

import pytest

from app.core.pipeline import AssistService
from app.integrations.amocrm.dialog_store import InMemoryDialogStore
from app.integrations.amocrm.models import NoteTarget, parse_webhook
from app.integrations.amocrm.notes import AmoCRMError, MockNotesClient
from app.integrations.amocrm.processor import WebhookProcessor
from app.kb.models import KnowledgeBase
from app.kb.retriever import make_retriever
from app.llm.fake import FakeLLM
from tests.integrations.amocrm.helpers import fixture, form


class Setup:
    def __init__(self, kb: KnowledgeBase, llm: FakeLLM | None = None) -> None:
        self.llm = llm or FakeLLM()
        self.store = InMemoryDialogStore()
        self.notes = MockNotesClient()
        self.processor = WebhookProcessor(
            AssistService(kb, make_retriever(kb), self.llm, timeout_s=5), self.store, self.notes
        )

    async def send(self, body: str) -> None:
        await self.processor.process(parse_webhook(body))


@pytest.fixture
def s(demo_kb: KnowledgeBase) -> Setup:
    return Setup(demo_kb)


async def test_incoming_message_writes_note_to_lead(s: Setup) -> None:
    await s.send(fixture("message_add_text_lead"))

    [note] = s.notes.notes()
    assert note.target == NoteTarget(entity="leads", id=4242)
    assert "💡 Подсказка" in note.text
    assert "690 ₽" in note.text  # черновик ответа из БЗ


async def test_doc_example_writes_note_to_contact(s: Setup) -> None:
    await s.send(fixture("message_add_doc"))

    [note] = s.notes.notes()
    assert note.target == NoteTarget(entity="contacts", id=123456789)


async def test_repeated_delivery_is_idempotent(s: Setup) -> None:
    body = fixture("message_add_text_lead")

    for _ in range(3):
        await s.send(body)

    assert len(s.notes.notes()) == 1
    assert len(s.llm.requests) == 1
    assert len(s.store.history("talk:117")) == 1


async def test_manager_messages_become_dialog_history_s7(s: Setup) -> None:
    await s.send(form("message", "m1", "Здравствуйте, интересует ноутбук X15"))
    await s.send(
        form("outgoing_message", "m2", "X15 в наличии, 89 990 ₽. Могу предложить сумку к нему")
    )
    await s.send(form("message", "m3", "Сумка не нужна, спасибо"))
    await s.send(form("message", "m4", "А когда сможете доставить?"))

    last_request = s.llm.requests[-1].context
    assert [t.role for t in last_request.dialog] == ["client", "manager", "client"]
    assert "product.bag" in last_request.facts.declined_product_ids
    assert "product.bag" not in [c.offer_id for c in last_request.candidates]
    assert len(s.notes.notes()) == 3  # на каждое сообщение клиента, не на реплику менеджера


async def test_attachment_without_text_is_stored_but_not_sent_to_llm(s: Setup) -> None:
    await s.send(form("message", "p1", "", attachment="picture"))

    assert s.llm.requests == []
    assert s.notes.notes() == []
    assert [t.text for t in s.store.history("talk:500")] == ["[вложение: picture]"]


async def test_chat_without_lead_or_contact_gets_no_note(
    s: Setup, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    await s.send(form("message", "c1", "Сколько стоит X15?", element_type="3"))

    assert s.notes.notes() == []
    assert len(s.llm.requests) == 1  # история и подсказка всё равно считаются
    assert "примечание не записано" in caplog.text


async def test_notes_error_is_logged_not_raised(
    demo_kb: KnowledgeBase, caplog: pytest.LogCaptureFixture
) -> None:
    setup = Setup(demo_kb)

    async def broken(target: NoteTarget, text: str) -> None:
        raise AmoCRMError("503")

    setup.notes.add_note = broken  # type: ignore[method-assign]
    caplog.set_level(logging.ERROR)

    await setup.send(fixture("message_add_text_lead"))

    assert "Не удалось обработать" in caplog.text


async def test_failed_message_can_be_retried(demo_kb: KnowledgeBase) -> None:
    setup = Setup(demo_kb)
    calls = 0
    real_add = setup.notes.add_note

    async def flaky(target: NoteTarget, text: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AmoCRMError("503")
        await real_add(target, text)

    setup.notes.add_note = flaky  # type: ignore[method-assign]
    body = fixture("message_add_text_lead")

    await setup.send(body)  # упало на записи примечания
    await setup.send(body)  # повторная доставка amoCRM — обрабатываем заново

    assert len(setup.notes.notes()) == 1
    assert len(setup.store.history("talk:117")) == 1


async def test_submit_and_drain_run_in_background(s: Setup) -> None:
    s.processor.submit(parse_webhook(fixture("message_add_text_lead")))

    assert s.notes.notes() == []  # ещё не обработано — submit не ждёт
    await s.processor.drain()
    assert len(s.notes.notes()) == 1


def test_history_is_bounded() -> None:
    store = InMemoryDialogStore(max_turns=3)
    from app.core.models import DialogTurn

    for i in range(5):
        store.append("k", DialogTurn(role="client", text=str(i)))

    assert [t.text for t in store.history("k")] == ["2", "3", "4"]
    assert store.history("other") == []

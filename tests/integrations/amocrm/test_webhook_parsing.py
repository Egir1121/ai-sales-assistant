"""Разбор вебхуков amoCRM на фикстурах из документации (SPEC §8, навык amocrm-integration)."""

import pytest

from app.integrations.amocrm.form import parse_form
from app.integrations.amocrm.models import NoteTarget, WebhookParseError, parse_webhook
from tests.integrations.amocrm.helpers import fixture


def test_parse_form_builds_nested_structure_with_lists() -> None:
    body = "a[b][0][c]=1&a[b][0][d][e]=x&a[b][1][c]=2&plain=%D0%BF%D1%80%D0%B8%D0%B2%D0%B5%D1%82"

    assert parse_form(body) == {
        "a": {"b": [{"c": "1", "d": {"e": "x"}}, {"c": "2"}]},
        "plain": "привет",
    }


def test_incoming_doc_example() -> None:
    webhook = parse_webhook(fixture("message_add_doc"))

    assert webhook.outgoing == []
    [msg] = webhook.incoming
    assert msg.id == "amo12345-31ed-41af-am23-conf1504"
    assert msg.talk_id == "117"
    assert msg.text == "Hello World!"
    assert msg.attachment is not None
    assert msg.attachment.type == "picture"
    assert msg.author is not None
    assert msg.author.type == "external"
    assert msg.origin == "telegram"
    # element_type=1 — чат привязан к контакту: примечание пишем в контакт
    assert msg.note_target == NoteTarget(entity="contacts", id=123456789)
    assert msg.dialog_key == "talk:117"


def test_outgoing_doc_example() -> None:
    webhook = parse_webhook(fixture("outgoing_message_add_doc"))

    assert webhook.incoming == []
    [msg] = webhook.outgoing
    assert msg.text == "Здравствуйте! Чем могу помочь?"
    assert msg.author is not None
    assert msg.author.type == "internal"
    assert msg.author.user_id == "123123"


def test_text_message_linked_to_lead() -> None:
    [msg] = parse_webhook(fixture("message_add_text_lead")).incoming

    assert msg.attachment is None
    assert msg.note_target == NoteTarget(entity="leads", id=4242)
    assert msg.history_text == "Сколько стоит доставка в Казань и можно оплатить при получении?"


def test_attachment_is_recorded_in_history_text() -> None:
    [msg] = parse_webhook(fixture("message_add_doc")).incoming

    assert msg.history_text == "Hello World! [вложение: picture]"


@pytest.mark.parametrize("element_type", ["3", "", None])
def test_no_note_target_for_other_entities(element_type: str | None) -> None:
    body = fixture("message_add_text_lead").replace("element_type%5D=2", "element_type%5D=3")
    if element_type is None:
        body = "&".join(p for p in body.split("&") if "element_" not in p)
    elif element_type == "":
        body = body.replace("element_type%5D=3", "element_type%5D=")

    [msg] = parse_webhook(body).incoming

    assert msg.note_target is None


def test_unknown_fields_are_ignored_and_other_events_skipped() -> None:
    body = (
        fixture("message_add_text_lead")
        + "&message%5Badd%5D%5B0%5D%5Bnew_field%5D=1&leads%5Bstatus%5D%5B0%5D%5Bid%5D=5"
    )

    webhook = parse_webhook(body)

    assert len(webhook.incoming) == 1


@pytest.mark.parametrize("body", ["message=oops", "message%5Badd%5D%5B0%5D%5Btext%5D=no-id"])
def test_broken_message_structure_raises(body: str) -> None:
    with pytest.raises(WebhookParseError):
        parse_webhook(body)


@pytest.mark.parametrize("body", ["", "not a form", "leads%5Bstatus%5D%5B0%5D%5Bid%5D=5"])
def test_body_without_messages_is_an_empty_webhook(body: str) -> None:
    webhook = parse_webhook(body)

    assert webhook.incoming == []
    assert webhook.outgoing == []

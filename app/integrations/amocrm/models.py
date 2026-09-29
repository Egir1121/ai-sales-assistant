"""Модели вебхука сообщений amoCRM. Только поля из документации (навык amocrm-integration);
незнакомые поля игнорируются, чтобы новые поля amoCRM не ломали приём."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.integrations.amocrm.form import parse_form

# Коды element_type в amoCRM: 1 — контакт, 2 — сделка. На странице вебхуков они не расшифрованы
# (в примере документации — "1"), проверить на реальном аккаунте (README, A19).
_NOTE_ENTITIES: dict[int, Literal["leads", "contacts"]] = {2: "leads", 1: "contacts"}


class WebhookParseError(ValueError):
    pass


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class AmoAuthor(_Lenient):
    id: str | None = None
    type: str | None = None
    name: str | None = None
    user_id: str | None = None


class AmoAttachment(_Lenient):
    type: str
    link: str | None = None
    file_name: str | None = None


class NoteTarget(_Lenient):
    entity: Literal["leads", "contacts"]
    id: int


class AmoMessage(_Lenient):
    id: str
    chat_id: str | None = None
    talk_id: str | None = None
    contact_id: str | None = None
    text: str = ""
    created_at: int | None = None
    message_type: str | None = None
    origin: str | None = None
    author: AmoAuthor | None = None
    attachment: AmoAttachment | None = None
    element_id: int | None = None
    element_type: int | None = None

    @field_validator("element_id", "element_type", "created_at", mode="before")
    @classmethod
    def _empty_to_none(cls, value: Any) -> Any:
        return None if value in ("", None) else value

    @property
    def dialog_key(self) -> str:
        """История хранится по talk_id (беседа), а если его нет — по chat_id."""
        return f"talk:{self.talk_id}" if self.talk_id else f"chat:{self.chat_id or self.id}"

    @property
    def history_text(self) -> str:
        parts = [self.text.strip()] if self.text.strip() else []
        if self.attachment:
            parts.append(f"[вложение: {self.attachment.type}]")
        return " ".join(parts)

    @property
    def note_target(self) -> NoteTarget | None:
        entity = _NOTE_ENTITIES.get(self.element_type or 0)
        if entity is None or not self.element_id:
            return None
        return NoteTarget(entity=entity, id=self.element_id)


class AmoWebhook(_Lenient):
    incoming: list[AmoMessage] = []
    outgoing: list[AmoMessage] = []


def parse_webhook(body: str) -> AmoWebhook:
    """`message[add]` — входящие от клиента, `outgoing_message[add]` — исходящие менеджера/бота.
    Остальные события игнорируются."""
    data = parse_form(body)
    try:
        return AmoWebhook(
            incoming=[AmoMessage.model_validate(m) for m in _added(data, "message")],
            outgoing=[AmoMessage.model_validate(m) for m in _added(data, "outgoing_message")],
        )
    except ValidationError as exc:
        raise WebhookParseError(str(exc)) from exc


def _added(data: dict[str, Any], event: str) -> list[Any]:
    section = data.get(event)
    if section is None:
        return []
    if not isinstance(section, dict) or not isinstance(section.get("add", []), list):
        raise WebhookParseError(f"неожиданная структура {event}")
    items: list[Any] = section.get("add", [])
    return items

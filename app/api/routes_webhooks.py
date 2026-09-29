"""Вебхук amoCRM (SPEC §8, ADR-004).

amoCRM ждёт ответ не дольше 2 секунд и отключает хук, если за 2 часа пришло больше 100
невалидных ответов. Поэтому: разбираем payload, ставим обработку в фон и сразу отвечаем 200 —
даже если payload не удалось разобрать (ошибку пишем в лог). 401 — только при неверном
секрете в URL: это ошибка настройки, её нужно заметить.
"""

import hmac
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import get_amocrm, get_settings
from app.config import Settings
from app.integrations.amocrm.models import NoteTarget, WebhookParseError, parse_webhook
from app.integrations.amocrm.notes import MockNotesClient
from app.integrations.amocrm.processor import WebhookProcessor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["amocrm"])


class WebhookAck(BaseModel):
    status: Literal["accepted", "ignored"]


@router.post("/webhooks/amocrm")
async def amocrm_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    processor: Annotated[WebhookProcessor, Depends(get_amocrm)],
    token: str = "",
) -> WebhookAck:
    secret = settings.amocrm_webhook_secret
    if secret and not hmac.compare_digest(token, secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid token")

    body = (await request.body()).decode("utf-8", errors="replace")
    try:
        webhook = parse_webhook(body)
    except WebhookParseError as exc:
        logger.warning("amoCRM: не удалось разобрать вебхук (%d байт): %s", len(body), exc)
        return WebhookAck(status="ignored")
    if not webhook.incoming and not webhook.outgoing:
        return WebhookAck(status="ignored")

    processor.submit(webhook)
    return WebhookAck(status="accepted")


class NoteView(BaseModel):
    target: NoteTarget
    text: str
    created_at: str


class NotesFeed(BaseModel):
    mode: str
    notes: list[NoteView]


@router.get("/v1/amocrm/notes")
def amocrm_notes(processor: Annotated[WebhookProcessor, Depends(get_amocrm)]) -> NotesFeed:
    """Лента примечаний mock-режима для демо-UI. В live примечания видны в самой amoCRM."""
    notes = processor.notes
    if not isinstance(notes, MockNotesClient):
        return NotesFeed(mode=notes.mode, notes=[])
    return NotesFeed(
        mode=notes.mode,
        notes=[
            NoteView(target=n.target, text=n.text, created_at=n.created_at.isoformat())
            for n in notes.notes()
        ],
    )

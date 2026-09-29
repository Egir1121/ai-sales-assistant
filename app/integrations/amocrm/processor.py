"""Фоновая обработка вебхуков amoCRM (ADR-004).

- Роут только разбирает payload и вызывает `submit` — ответ amoCRM уходит сразу (лимит 2 с).
- Идемпотентность по `message.id`: повторная доставка того же сообщения не создаёт второе
  примечание. Сообщение помечается обработанным только после успеха, поэтому повтор после
  сбоя (amoCRM повторит доставку) обработается заново.
- Реплики менеджера (`outgoing_message`) только пополняют историю: так сервис видит,
  что уже предлагали, и не повторяет отклонённое.
- Сообщение без текста (картинка, стикер) в LLM не уходит — в истории остаётся `[вложение: …]`.
- Беседы обрабатываются последовательно (блокировка на talk_id), чтобы не перепутать порядок.
- Любая ошибка логируется и не выходит наружу.
"""

import asyncio
import logging
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable

from app.core.models import AssistRequest, DialogTurn, Lead
from app.core.pipeline import AssistService
from app.integrations.amocrm.dialog_store import DialogStore
from app.integrations.amocrm.formatting import format_note
from app.integrations.amocrm.models import AmoMessage, AmoWebhook
from app.integrations.amocrm.notes import NotesClient

logger = logging.getLogger(__name__)


class _SeenIds:
    """Ограниченное множество обработанных message.id (старые вытесняются)."""

    def __init__(self, capacity: int = 50_000) -> None:
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._capacity = capacity

    def __contains__(self, message_id: object) -> bool:
        return message_id in self._ids

    def add(self, message_id: str) -> None:
        self._ids[message_id] = None
        if len(self._ids) > self._capacity:
            self._ids.popitem(last=False)


class WebhookProcessor:
    def __init__(self, assist: AssistService, store: DialogStore, notes: NotesClient) -> None:
        self._assist = assist
        self._store = store
        self.notes = notes
        self._seen = _SeenIds()
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, webhook: AmoWebhook) -> None:
        """Запустить обработку в фоне и сразу вернуть управление."""
        task = asyncio.create_task(self.process(webhook))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Дождаться фоновых задач (тесты и корректная остановка сервиса)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def process(self, webhook: AmoWebhook) -> None:
        for message in webhook.outgoing:
            await self._safely(message, self._handle_outgoing)
        for message in webhook.incoming:
            await self._safely(message, self._handle_incoming)

    async def _safely(
        self, message: AmoMessage, handler: Callable[[AmoMessage], Awaitable[None]]
    ) -> None:
        async with self._locks[message.dialog_key]:
            if message.id in self._seen:
                logger.info("amoCRM: повторная доставка %s — пропускаем", message.id)
                return
            try:
                await handler(message)
            except Exception:
                logger.exception("Не удалось обработать сообщение amoCRM %s", message.id)
                return
            self._seen.add(message.id)

    async def _handle_outgoing(self, message: AmoMessage) -> None:
        if message.history_text:
            self._store.append(
                message.dialog_key, DialogTurn(role="manager", text=message.history_text)
            )

    async def _handle_incoming(self, message: AmoMessage) -> None:
        history = self._store.history(message.dialog_key)
        if not message.text.strip():
            self._store.append(
                message.dialog_key, DialogTurn(role="client", text=message.history_text)
            )
            logger.info("amoCRM: сообщение %s без текста — в LLM не отправляем", message.id)
            return

        target = message.note_target
        lead_id = target.id if target and target.entity == "leads" else None
        response = await self._assist.assist(
            AssistRequest(message=message.text, dialog=history, lead=Lead(id=lead_id))
        )
        if target is None:
            logger.warning(
                "amoCRM: чат %s не привязан к сделке или контакту (element_type=%s) — "
                "примечание не записано",
                message.dialog_key,
                message.element_type,
            )
        else:
            await self.notes.add_note(target, format_note(response))
        # в историю — только после успеха, иначе повторная доставка задвоит реплику
        self._store.append(message.dialog_key, DialogTurn(role="client", text=message.history_text))

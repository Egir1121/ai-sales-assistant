"""Запись результата в amoCRM примечанием (SPEC §8, навык amocrm-integration).

`POST https://{subdomain}.amocrm.ru/api/v4/{leads|contacts}/{id}/notes`, тело — массив
`[{"note_type": "common", "params": {"text": ...}}]`, авторизация `Bearer <долгосрочный токен>`.
Тип `common` выбран как самый простой и точно документированный (ADR-004).
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import httpx2

from app.integrations.amocrm.models import NoteTarget

logger = logging.getLogger(__name__)


class AmoCRMError(Exception):
    pass


@dataclass(frozen=True)
class Note:
    target: NoteTarget
    text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class NotesClient(Protocol):
    mode: str

    async def add_note(self, target: NoteTarget, text: str) -> None: ...

    async def aclose(self) -> None: ...


class MockNotesClient:
    """AMOCRM_MODE=mock: примечание пишется в лог и в ленту демо-UI, в сеть не ходит."""

    mode = "mock"

    def __init__(self, max_notes: int = 100) -> None:
        self._notes: deque[Note] = deque(maxlen=max_notes)

    async def add_note(self, target: NoteTarget, text: str) -> None:
        self._notes.appendleft(Note(target=target, text=text))
        logger.info("[mock amoCRM] примечание в %s/%d:\n%s", target.entity, target.id, text)

    def notes(self) -> list[Note]:
        """Свежие сверху."""
        return list(self._notes)

    async def aclose(self) -> None:
        return None


class LiveNotesClient:
    """AMOCRM_MODE=live: реальный вызов API amoCRM."""

    mode = "live"

    def __init__(
        self,
        subdomain: str,
        access_token: str,
        timeout_s: float = 10.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=f"https://{subdomain}.amocrm.ru",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout_s,
            transport=transport,
        )

    async def add_note(self, target: NoteTarget, text: str) -> None:
        url = f"/api/v4/{target.entity}/{target.id}/notes"
        body = [{"note_type": "common", "params": {"text": text}}]
        try:
            response = await self._client.post(url, json=body)
        except httpx2.HTTPError as exc:
            raise AmoCRMError(f"нет связи с amoCRM: {exc!r}") from exc
        if response.is_error:
            raise AmoCRMError(
                f"amoCRM вернул {response.status_code} на {url}: {response.text[:300]}"
            )
        logger.info("Примечание записано в %s/%d", target.entity, target.id)

    async def aclose(self) -> None:
        await self._client.aclose()

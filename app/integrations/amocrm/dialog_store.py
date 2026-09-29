"""История диалога по talk_id/chat_id. In-memory по умолчанию; протокол позволяет заменить
на Redis/SQLite без изменений в обработчике (персистентность — вне скоупа, SPEC §12)."""

from collections import OrderedDict, deque
from typing import Protocol

from app.core.models import DialogTurn


class DialogStore(Protocol):
    def history(self, key: str) -> list[DialogTurn]: ...

    def append(self, key: str, turn: DialogTurn) -> None: ...


class InMemoryDialogStore:
    def __init__(self, max_turns: int = 50, max_dialogs: int = 10_000) -> None:
        self._max_turns = max_turns
        self._max_dialogs = max_dialogs
        self._dialogs: OrderedDict[str, deque[DialogTurn]] = OrderedDict()

    def history(self, key: str) -> list[DialogTurn]:
        return list(self._dialogs.get(key, ()))

    def append(self, key: str, turn: DialogTurn) -> None:
        dialog = self._dialogs.get(key)
        if dialog is None:
            dialog = self._dialogs[key] = deque(maxlen=self._max_turns)
            if len(self._dialogs) > self._max_dialogs:
                self._dialogs.popitem(last=False)  # вытесняем самую старую беседу
        self._dialogs.move_to_end(key)
        dialog.append(turn)

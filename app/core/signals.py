"""Детерминированный словарь жалоб и требований возврата — второй сигнал подавления допродажи.

Нужен, чтобы инвариант 3 не зависел только от классификации LLM (допущение A14).
Нейтральные вопросы о правилах возврата («как вернуть, если не подойдёт?») сигналом не считаются.
"""

import re
from typing import Literal

Signal = Literal["complaint", "refund"]

_COMPLAINT = re.compile(
    r"сломал|не работает|не включается|брак|ужас|кошмар|отвратительн|безобраз|обман|"
    r"жалоб|претензи|разочарован|хамств|возмутительн|верх наглости|"
    r"\bbroken\b|\bterrible\b|\bawful\b|\bcomplain|\bscam\b|\bdisgusting\b",
    re.IGNORECASE,
)
_REFUND = re.compile(
    r"верните\s+деньги|вернуть\s+деньги|хочу\s+вернуть|оформить\s+возврат|требую\s+возврат|"
    r"деньги\s+назад|\brefund\b|\bmoney back\b",
    re.IGNORECASE,
)


def negative_signals(text: str) -> set[Signal]:
    signals: set[Signal] = set()
    if _COMPLAINT.search(text):
        signals.add("complaint")
    if _REFUND.search(text):
        signals.add("refund")
    return signals

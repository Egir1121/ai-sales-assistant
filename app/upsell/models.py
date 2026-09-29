from dataclasses import dataclass
from typing import Protocol

from app.kb.models import Intent


class Turn(Protocol):
    """Реплика диалога. Структурный тип: подходит `core.models.DialogTurn` и любая похожая."""

    @property
    def role(self) -> str: ...

    @property
    def text(self) -> str: ...


@dataclass(frozen=True)
class DialogFacts:
    """Что код понял из истории чата — детерминированно, до LLM."""

    deal_product_ids: frozenset[str]
    """Товары сделки: из lead + упомянутые клиентом + основной товар из реплик менеджера."""
    offered_product_ids: frozenset[str]
    """Что менеджер уже предлагал (товары-предложения из его реплик)."""
    declined_product_ids: frozenset[str]
    """От чего клиент отказался и потом не передумал."""
    client_tokens: tuple[str, ...]
    """Токены всех реплик клиента, включая текущее сообщение (для правил по ключевым словам)."""


@dataclass(frozen=True)
class UpsellCandidate:
    offer_id: str
    title: str
    price: int
    currency: str
    rule_id: str
    why: str
    if_intents_any: tuple[Intent, ...]
    never_if_intents: tuple[Intent, ...]
    already_offered: bool

    def allowed_for(self, intent: Intent) -> bool:
        if intent in self.never_if_intents:
            return False
        return not self.if_intents_any or intent in self.if_intents_any

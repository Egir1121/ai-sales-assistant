"""Guardrails (SPEC §6.5): код проверяет ответ LLM и исправляет то, что нарушает инварианты.

Каждое правило — функция `(draft, ctx) -> bool` («сработало ли»), меняет `draft` на месте.
`apply_guardrails` прогоняет их по порядку и возвращает имена сработавших — они попадают
в `meta.guardrails_applied`, в evals и в логи.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.signals import injection_signal, negative_signals
from app.kb.models import Intent, KnowledgeBase, Sentiment
from app.kb.text import contains_phrase, extract_numbers, mention_tokens
from app.llm.schema import LLMUpsell
from app.upsell.models import UpsellCandidate

MAX_UPSELL = 2
SUPPRESS_INTENTS = frozenset({Intent.COMPLAINT, Intent.REFUND})


@dataclass
class Draft:
    """Изменяемый черновик ответа между LLM и финальной сборкой."""

    reply_text: str
    kb_refs: list[str]
    needs_manager: bool
    intent: Intent
    sentiment: Sentiment
    summary: str
    upsell: list[LLMUpsell]
    upsell_suppressed_reason: str | None
    declined_offer_ids: list[str]
    next_best_action: str
    risk_flags: list[str] = field(default_factory=list)

    def flag(self, name: str) -> None:
        if name not in self.risk_flags:
            self.risk_flags.append(name)


@dataclass(frozen=True)
class GuardrailContext:
    kb: KnowledgeBase
    candidates: tuple[UpsellCandidate, ...]
    declined_offer_ids: frozenset[str]
    """Отказы, найденные кодом в диалоге."""
    message: str
    source_texts: tuple[str, ...]
    """Диалог и текущее сообщение — числа из них тоже считаются проверенными."""


Guardrail = Callable[[Draft, GuardrailContext], bool]


def filter_kb_refs(draft: Draft, ctx: GuardrailContext) -> bool:
    """Все `kb_refs` существуют в БЗ (ссылаться можно на faq/product/policy), без дублей."""
    valid = list(dict.fromkeys(r for r in draft.kb_refs if ctx.kb.get(r) is not None))
    changed = valid != draft.kb_refs
    draft.kb_refs = valid
    return changed


def filter_offers(draft: Draft, ctx: GuardrailContext) -> bool:
    """`offer_id` ⊆ кандидатов, не из отклонённых, и интентное условие правила выполнено."""
    candidates = {c.offer_id: c for c in ctx.candidates}
    declined = ctx.declined_offer_ids | set(draft.declined_offer_ids)
    kept: list[LLMUpsell] = []
    for o in draft.upsell:
        candidate = candidates.get(o.offer_id)
        if (
            candidate is None
            or o.offer_id in declined
            or not candidate.allowed_for(draft.intent)
            or any(k.offer_id == o.offer_id for k in kept)
        ):
            continue
        kept.append(o)
    changed = len(kept) != len(draft.upsell)
    draft.upsell = kept
    return changed


def suppress_upsell(draft: Draft, ctx: GuardrailContext) -> bool:
    """Жалоба, возврат, негатив, попытка инъекции (по LLM или по словарю) и непонятный
    запрос → допродажи нет."""
    signals = negative_signals(ctx.message)
    injection = injection_signal(ctx.message) or "prompt_injection" in draft.risk_flags
    if injection:
        draft.flag("prompt_injection")
    if signals:
        draft.sentiment = "negative"  # словарь сильнее «нейтрального» тона от LLM
    reason: str | None = None
    if draft.intent in SUPPRESS_INTENTS or signals:
        reason = "Жалоба или возврат: сначала решить проблему клиента, допродажа неуместна"
        if signals and draft.intent not in SUPPRESS_INTENTS:
            draft.flag("complaint_signal")
    elif draft.sentiment == "negative":
        reason = "Негативный тон клиента: допродажа сейчас оттолкнёт"
    elif injection:
        reason = "В сообщении попытка управлять ассистентом: ответить по делу, без допродажи"
    elif draft.intent == Intent.UNCLEAR:
        reason = "Запрос непонятен: сначала уточнить, что нужно клиенту"
    if reason is None:
        return False

    draft.upsell = []
    draft.upsell_suppressed_reason = reason
    reply_tokens = mention_tokens(draft.reply_text)
    for candidate in ctx.candidates:
        if any(contains_phrase(reply_tokens, alias) for alias in _mentions(ctx.kb, candidate)):
            draft.flag("upsell_in_reply")
            draft.needs_manager = True
            break
    return True


def _mentions(kb: KnowledgeBase, candidate: UpsellCandidate) -> tuple[tuple[str, ...], ...]:
    return kb.product_mentions.get(candidate.offer_id, ())


def check_numbers(draft: Draft, ctx: GuardrailContext) -> bool:
    """Каждое число в ответе клиенту есть в БЗ или в диалоге; иначе — флаг и needs_manager."""
    allowed = ctx.kb.numbers | {n for text in ctx.source_texts for n in extract_numbers(text)}
    if extract_numbers(draft.reply_text) <= allowed:
        return False
    draft.flag("unverified_number")
    draft.needs_manager = True
    return True


def check_unanswered_numbers(draft: Draft, ctx: GuardrailContext) -> bool:
    """Число из вопроса клиента, которого нет ни в БЗ, ни в ответе («рассрочка на 36 месяцев»,
    «iPhone 17»), значит, ответ на этот вопрос не дан → нужен менеджер."""
    reply_numbers = extract_numbers(draft.reply_text)
    missing = extract_numbers(ctx.message) - ctx.kb.numbers - reply_numbers
    if not missing:
        return False
    draft.flag("unanswered_number")
    draft.needs_manager = True
    return True


def cap_upsell(draft: Draft, ctx: GuardrailContext) -> bool:
    if len(draft.upsell) <= MAX_UPSELL:
        return False
    draft.upsell = sorted(draft.upsell, key=lambda o: o.confidence, reverse=True)[:MAX_UPSELL]
    return True


GUARDRAILS: tuple[tuple[str, Guardrail], ...] = (
    ("kb_refs_filtered", filter_kb_refs),
    ("offers_filtered", filter_offers),
    ("upsell_suppressed", suppress_upsell),
    ("unverified_number", check_numbers),
    ("unanswered_number", check_unanswered_numbers),
    ("upsell_capped", cap_upsell),
)


def apply_guardrails(draft: Draft, ctx: GuardrailContext) -> list[str]:
    return [name for name, guardrail in GUARDRAILS if guardrail(draft, ctx)]


__all__ = [
    "GUARDRAILS",
    "Draft",
    "GuardrailContext",
    "apply_guardrails",
    "cap_upsell",
    "check_numbers",
    "check_unanswered_numbers",
    "extract_numbers",
    "filter_kb_refs",
    "filter_offers",
    "suppress_upsell",
]

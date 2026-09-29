"""FakeLLM — детерминированный офлайн-провайдер (ADR-005, инвариант 6).

Работает по структурированному `PromptContext`: интент по словарю, ответ — дословно из найденных
записей БЗ, допродажа — первые подходящие кандидаты. Качество формулировок он не измеряет —
для этого прогон на реальной модели. Для тестов умеет вернуть заданный ответ, упасть, «зависнуть».
"""

import asyncio
import re

from app.core.language import detect_language
from app.core.signals import Signal, negative_signals
from app.kb.models import FaqEntry, Intent, KBEntry, KnowledgeBase, Policy, Product, Sentiment
from app.kb.retriever import KeywordRetriever
from app.llm.base import LLMRequest, LLMResult, PromptContext
from app.llm.prompts import format_price
from app.llm.schema import LLMOutput, LLMUpsell

_I = re.IGNORECASE
_DISCOUNT = re.compile(r"скидк|дешевле|discount", _I)
_OBJECTION = re.compile(r"дорог|expensive", _I)
_ORDER = re.compile(r"\bберу\b|возьму|оформ|куплю|покупаю|\bbuy\b|\border\b", _I)
_DELIVERY_PAYMENT = re.compile(
    r"достав|привез|самовывоз|оплат|рассрочк|кредит|сдэк|delivery|shipping|\bpay", _I
)
_PRICE = re.compile(r"сколько стоит|цена|стоимост|почем|\bprice\b|how much", _I)
_GREETING = re.compile(r"^\W*(здравствуйте|привет|добрый (день|вечер)|hello|hi)\W*$", _I)
_POSITIVE = re.compile(r"спасибо|отлично|супер|thank|great", _I)
_INJECTION = re.compile(r"игнорируй|забудь (все|правила)|ignore (all|previous)|system prompt", _I)
_PARTS = re.compile(r"[?.!;\n]|\s+и\s+|,\s*(?:а|и)\s+", _I)

MIN_SCORE = 2.0
MAX_REFS = 3

_INTENT_RU = {
    Intent.PRODUCT_QUESTION: "Вопрос о товаре",
    Intent.PRICE_QUESTION: "Вопрос о цене",
    Intent.DELIVERY_PAYMENT_QUESTION: "Вопрос о доставке/оплате",
    Intent.ORDER_INTENT: "Готов оформить заказ",
    Intent.DISCOUNT_REQUEST: "Просит скидку",
    Intent.PRICE_OBJECTION: "Считает, что дорого",
    Intent.COMPLAINT: "Жалоба",
    Intent.REFUND: "Хочет вернуть товар/деньги",
    Intent.SMALLTALK: "Приветствие",
    Intent.UNCLEAR: "Непонятный запрос",
    Intent.OTHER: "Вопрос вне типовых тем",
}

_NEXT_ACTION = {
    Intent.ORDER_INTENT: "Подтвердить состав заказа, адрес и способ оплаты",
    Intent.DELIVERY_PAYMENT_QUESTION: "Уточнить адрес и предложить оформить заказ сегодня",
    Intent.PRICE_QUESTION: "Уточнить конфигурацию и предложить оформить заказ",
    Intent.DISCOUNT_REQUEST: "Не обещать скидку; согласовать по политике policy.discount",
    Intent.PRICE_OBJECTION: "Предложить рассрочку или комплект вместо скидки",
    Intent.COMPLAINT: "Извиниться, оформить обращение в сервис, ничего не предлагать",
    Intent.REFUND: "Проверить условия возврата и передать руководителю сервиса",
    Intent.UNCLEAR: "Дождаться уточнения от клиента",
}


class FakeLLM:
    provider = "fake"
    model = "fake-heuristic-v1"

    def __init__(
        self,
        output: LLMOutput | None = None,
        error: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self._output = output
        self._error = error
        self._delay_s = delay_s
        self._rankers: dict[int, KeywordRetriever] = {}
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._error:
            raise self._error
        output = self._output or self._heuristic(request.context)
        return LLMResult(output=output, provider=self.provider, model=self.model)

    def _ranker(self, kb: KnowledgeBase) -> KeywordRetriever:
        return self._rankers.setdefault(id(kb), KeywordRetriever(kb))

    def _heuristic(self, ctx: PromptContext) -> LLMOutput:
        signals = negative_signals(ctx.message)
        language = detect_language(ctx.message) or "ru"
        intent = _classify(ctx, signals)
        sentiment: Sentiment = (
            "negative"
            if signals or intent in (Intent.COMPLAINT, Intent.REFUND)
            else "positive"
            if _POSITIVE.search(ctx.message)
            else "neutral"
        )
        # жалоба/возврат и не-русский язык отвечаются шаблоном — на записи БЗ они не опираются
        templated = intent in (Intent.COMPLAINT, Intent.REFUND) or language != "ru"
        refs = [] if templated else self._refs(ctx)
        reply, needs_manager = _reply(ctx, intent, refs, language)
        risk_flags = ["prompt_injection"] if _INJECTION.search(ctx.message) else []
        if intent == Intent.DISCOUNT_REQUEST:
            risk_flags.append("discount_request")

        return LLMOutput(
            language=language,
            intent=intent,
            sentiment=sentiment,
            client_reply=reply,
            kb_refs=[e.id for e in refs],
            needs_manager=needs_manager,
            summary=_summary(ctx, intent),
            upsell=_upsell(ctx, intent, sentiment),
            declined_offer_ids=[],
            next_best_action=_NEXT_ACTION.get(intent, "Ответить на вопрос и уточнить потребность"),
            risk_flags=risk_flags,
        )

    def _refs(self, ctx: PromptContext) -> list[KBEntry]:
        """Лучшая запись на каждую часть сообщения — так покрываются несколько вопросов (S8)."""
        ranker = self._ranker(ctx.kb)
        refs: list[KBEntry] = []
        for part in [ctx.message, *_PARTS.split(ctx.message)]:
            hits = ranker.rank(part)
            if hits and hits[0].score >= MIN_SCORE and hits[0].entry not in refs:
                refs.append(hits[0].entry)
        # целое сообщение даёт лучшую запись первой; части добавляют остальные вопросы
        return refs[:MAX_REFS]


def _classify(ctx: PromptContext, signals: set[Signal]) -> Intent:
    text = ctx.message
    if "complaint" in signals:
        return Intent.COMPLAINT
    if "refund" in signals:
        return Intent.REFUND
    for pattern, intent in (
        (_DISCOUNT, Intent.DISCOUNT_REQUEST),
        (_OBJECTION, Intent.PRICE_OBJECTION),
        (_ORDER, Intent.ORDER_INTENT),
        (_DELIVERY_PAYMENT, Intent.DELIVERY_PAYMENT_QUESTION),
        (_PRICE, Intent.PRICE_QUESTION),
        (_GREETING, Intent.SMALLTALK),
    ):
        if pattern.search(text):
            return intent
    if any(isinstance(h.entry, Product) for h in ctx.retrieval.hits):
        return Intent.PRODUCT_QUESTION
    return Intent.OTHER if ctx.retrieval.hits or len(text.split()) > 2 else Intent.UNCLEAR


def _reply(
    ctx: PromptContext, intent: Intent, refs: list[KBEntry], language: str
) -> tuple[str, bool]:
    name = ctx.client_name
    if language != "ru":
        greeting = f"Hello, {name}!" if name and name.isascii() else "Hello!"
        text = (
            "Thank you for your message. A manager will get back to you shortly with the details."
        )
        return f"{greeting} {text}", True

    greeting = f"{name}, здравствуйте!" if name else "Здравствуйте!"
    if intent == Intent.COMPLAINT:
        body = (
            "Очень жаль, что так вышло. Передам вашу ситуацию ответственному специалисту, "
            "и мы свяжемся с вами в ближайшее время."
        )
        return f"{greeting} {body}", True
    if intent == Intent.REFUND:
        body = (
            "Понимаю вас. Передам запрос на возврат ответственному специалисту и вернусь с ответом."
        )
        return f"{greeting} {body}", True
    if intent == Intent.DISCOUNT_REQUEST:
        return f"{greeting} Передам ваш запрос по скидке руководителю и вернусь с ответом.", True
    if intent == Intent.SMALLTALK:
        return f"{greeting} Чем могу помочь?", False
    if intent == Intent.UNCLEAR:
        return f"{greeting} Уточните, пожалуйста, что вас интересует?", False

    facts = [_fact(e) for e in refs if not isinstance(e, Policy)]
    if not facts:
        return f"{greeting} Уточню этот вопрос и вернусь с ответом.", True
    return " ".join([greeting, *facts]), False


def _fact(entry: FaqEntry | Product) -> str:
    if isinstance(entry, FaqEntry):
        return entry.answer
    stock = "есть в наличии" if entry.in_stock else "сейчас нет в наличии"
    return f"{entry.title} стоит {format_price(entry.price, entry.currency)}, {stock}."


def _summary(ctx: PromptContext, intent: Intent) -> str:
    kb = ctx.kb
    parts = [_INTENT_RU[intent] + "."]
    if ctx.facts.deal_product_ids:
        titles = sorted(kb.product(pid).title for pid in ctx.facts.deal_product_ids)
        parts.append(f"Интересуется: {', '.join(titles)}.")
    if ctx.facts.declined_product_ids:
        titles = sorted(kb.product(pid).title for pid in ctx.facts.declined_product_ids)
        parts.append(f"Отказался: {', '.join(titles)}.")
    return " ".join(parts)


def _upsell(ctx: PromptContext, intent: Intent, sentiment: Sentiment) -> list[LLMUpsell]:
    if sentiment == "negative" or intent in (Intent.COMPLAINT, Intent.REFUND, Intent.UNCLEAR):
        return []
    fresh_first = sorted(
        (c for c in ctx.candidates if c.allowed_for(intent)), key=lambda c: c.already_offered
    )
    when = (
        "После подтверждения заказа"
        if intent == Intent.ORDER_INTENT
        else "После ответа на вопрос клиента"
    )
    return [
        LLMUpsell(
            offer_id=c.offer_id,
            reason="",
            pitch=f"Кстати, к покупке можно добавить: {c.title}.",
            when_to_say=when,
            confidence=(0.3 if c.already_offered else 0.6 - 0.1 * i),
        )
        for i, c in enumerate(fresh_first[:2])
    ]

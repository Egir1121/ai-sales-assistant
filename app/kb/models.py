"""Pydantic-схема базы знаний — источник правды (SPEC §5 и навык kb-edit должны с ней совпадать).

Ошибки полей ловит Pydantic, ссылочную целостность — `KnowledgeBase._check_integrity`.
Все проблемы целостности собираются и сообщаются разом.
"""

import re
from collections import defaultdict
from enum import StrEnum
from functools import cached_property
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    model_validator,
)

from app.kb.text import extract_numbers, tokenize

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Intent(StrEnum):
    """Словарь интентов: общий для правил БЗ, ответа LLM и guardrails."""

    PRODUCT_QUESTION = "product_question"
    PRICE_QUESTION = "price_question"
    DELIVERY_PAYMENT_QUESTION = "delivery_payment_question"
    ORDER_INTENT = "order_intent"
    DISCOUNT_REQUEST = "discount_request"
    PRICE_OBJECTION = "price_objection"
    COMPLAINT = "complaint"
    REFUND = "refund"
    SMALLTALK = "smalltalk"
    UNCLEAR = "unclear"
    OTHER = "other"


Sentiment = Literal["positive", "neutral", "negative"]


def _prefixed_id(prefix: str) -> AfterValidator:
    pattern = re.compile(rf"{prefix}\.[a-z0-9_]+")

    def check(value: str) -> str:
        if not pattern.fullmatch(value):
            raise ValueError(
                f"id должен иметь вид '{prefix}.snake_case' (латиница), получено {value!r}"
            )
        return value

    return AfterValidator(check)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Company(_Strict):
    name: NonEmptyStr
    tone: NonEmptyStr
    signature: NonEmptyStr
    fallback_reply: NonEmptyStr


class FaqEntry(_Strict):
    kind: ClassVar[str] = "faq"
    id: Annotated[str, _prefixed_id("faq")]
    questions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    answer: NonEmptyStr


class Product(_Strict):
    kind: ClassVar[str] = "product"
    id: Annotated[str, _prefixed_id("product")]
    title: NonEmptyStr
    price: NonNegativeInt
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "RUB"
    tags: tuple[NonEmptyStr, ...] = ()
    aliases: tuple[NonEmptyStr, ...] = Field(min_length=1)
    description: str = ""
    in_stock: bool = True


class Policy(_Strict):
    kind: ClassVar[str] = "policy"
    id: Annotated[str, _prefixed_id("policy")]
    text: NonEmptyStr


class UpsellRule(_Strict):
    id: Annotated[str, _prefixed_id("rule")]
    if_product_tags_any: tuple[NonEmptyStr, ...] = ()
    if_message_keywords_any: tuple[NonEmptyStr, ...] = ()
    if_intents_any: tuple[Intent, ...] = ()  # пусто = любой интент
    offer_id: NonEmptyStr
    why: NonEmptyStr
    never_if_intents: tuple[Intent, ...] = (Intent.COMPLAINT, Intent.REFUND)

    @model_validator(mode="after")
    def _has_trigger(self) -> Self:
        if not self.if_product_tags_any and not self.if_message_keywords_any:
            raise ValueError(
                "нужно хотя бы одно условие: if_product_tags_any или if_message_keywords_any"
            )
        return self


KBEntry = FaqEntry | Product | Policy


class KnowledgeBase(_Strict):
    version: Literal[1]
    company: Company
    faq: tuple[FaqEntry, ...] = ()
    products: tuple[Product, ...] = ()
    policies: tuple[Policy, ...] = ()
    upsell_rules: tuple[UpsellRule, ...] = ()

    @cached_property
    def entries(self) -> tuple[KBEntry, ...]:
        """Записи, на которые можно ссылаться из ответа (`kb_refs`), в порядке файла."""
        return (*self.faq, *self.products, *self.policies)

    @cached_property
    def _by_id(self) -> dict[str, KBEntry]:
        return {entry.id: entry for entry in self.entries}

    @cached_property
    def product_mentions(self) -> dict[str, tuple[tuple[str, ...], ...]]:
        """Токенизированные алиасы и название каждого товара — для поиска упоминаний в тексте."""
        return {
            p.id: tuple(tuple(tokenize(a)) for a in (*p.aliases, p.title)) for p in self.products
        }

    @cached_property
    def numbers(self) -> frozenset[str]:
        """Все числа, которые встречаются в БЗ, — для числового контроля ответа."""
        texts = [self.company.name, self.company.fallback_reply]
        for f in self.faq:
            texts += [*f.questions, f.answer]
        for p in self.products:
            texts += [p.title, *p.aliases, p.description, str(p.price)]
        texts += [policy.text for policy in self.policies]
        return frozenset(n for text in texts for n in extract_numbers(text))

    def get(self, entry_id: str) -> KBEntry | None:
        return self._by_id.get(entry_id)

    def product(self, product_id: str) -> Product:
        entry = self._by_id.get(product_id)
        if not isinstance(entry, Product):
            raise KeyError(product_id)
        return entry

    @model_validator(mode="after")
    def _check_integrity(self) -> Self:
        problems = [
            *self._duplicate_ids(),
            *self._broken_rules(),
            *self._alias_collisions(),
        ]
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def _duplicate_ids(self) -> list[str]:
        seen: set[str] = set()
        problems = []
        for entry_id in [e.id for e in self.entries] + [r.id for r in self.upsell_rules]:
            if entry_id in seen:
                problems.append(f"дублируется id: {entry_id}")
            seen.add(entry_id)
        return problems

    def _broken_rules(self) -> list[str]:
        product_ids = {p.id for p in self.products}
        known_tags = {tag for p in self.products for tag in p.tags}
        problems = []
        for rule in self.upsell_rules:
            if rule.offer_id not in product_ids:
                problems.append(
                    f"{rule.id}: offer_id {rule.offer_id!r} не найден среди products "
                    "(предлагать можно только товар или услугу из БЗ)"
                )
            problems += [
                f"{rule.id}: тег {tag!r} из if_product_tags_any нет ни у одного товара"
                for tag in rule.if_product_tags_any
                if tag not in known_tags
            ]
        return problems

    def _alias_collisions(self) -> list[str]:
        owners: defaultdict[str, set[str]] = defaultdict(set)
        for product in self.products:
            for alias in product.aliases:
                owners[" ".join(tokenize(alias))].add(product.id)
        return [
            f"алиас {alias!r} используется в нескольких товарах: {', '.join(sorted(ids))}"
            for alias, ids in owners.items()
            if len(ids) > 1
        ]

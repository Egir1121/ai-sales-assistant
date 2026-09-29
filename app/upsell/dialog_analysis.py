"""Анализ истории чата: товары сделки, что предлагал менеджер, от чего отказался клиент.

Отказ определяется по фрагментам реплики клиента (делим по знакам препинания и «а/но»):
- фрагмент с товаром и маркером отказа («сумка не нужна», «без мышки») → отказ от этого товара;
- фрагмент без товара с общим отказом («нет, спасибо», «не надо») → отказ от последних
  предложений менеджера, кроме тех, что клиент в той же реплике принял;
- фрагмент с товаром без отказа (вопрос о нём, «сумку беру») → интерес, прежний отказ снимается.
Вопросы («а X13 нет в наличии?») отказом не считаются.

Это эвристика, поэтому guardrails дополнительно объединяют её с `declined_offer_ids` от LLM:
объединение только сужает допродажу (ADR-002).
"""

import re
from collections.abc import Iterable, Sequence

from app.kb.models import KnowledgeBase
from app.kb.text import contains_phrase, mention_tokens, normalize, tokenize
from app.upsell.models import DialogFacts, Turn

_SEGMENT_SPLIT = re.compile(r"(?<=[.,;:!?])\s*|\s+(?=\b(?:а|но|but)\b)")

_GENERAL_REFUSAL = re.compile(
    r"^(?:нет|неа|не)\b"
    r"|\bне\s+(?:нужн\w*|надо|интерес\w*|хочу|буду|стоит|требуется)"
    r"|\bоткаж\w*|\bотказыва\w*|\bобойд\w*|\bлишн\w*"
    r"|^no\b|\bno thanks\b|\bnot (?:needed|interested)\b|\bdon'?t need\b"
)
_PRODUCT_REFUSAL = re.compile(_GENERAL_REFUSAL.pattern + r"|\bбез\b|\bwithout\b")
_ACCEPTANCE = re.compile(
    r"(?<!не )\b(?:беру|возьму|берем|давайте|добавьте|добавь|оформляйте|хочу|нужн[аоы]?|yes|ok)\b"
)


def _segments(text: str) -> list[str]:
    return [s for s in _SEGMENT_SPLIT.split(normalize(text)) if s and s.strip()]


def mentioned_products(kb: KnowledgeBase, text: str) -> set[str]:
    tokens = mention_tokens(text)
    return {
        product_id
        for product_id, aliases in kb.product_mentions.items()
        if any(contains_phrase(tokens, alias) for alias in aliases)
    }


def _offer_ids(kb: KnowledgeBase) -> frozenset[str]:
    return frozenset(rule.offer_id for rule in kb.upsell_rules)


def analyze_dialog(
    kb: KnowledgeBase,
    dialog: Sequence[Turn],
    message: str,
    lead_product_ids: Iterable[str] = (),
) -> DialogFacts:
    offers = _offer_ids(kb)
    deal = {pid for pid in lead_product_ids if kb.get(pid) is not None}
    offered: set[str] = set()
    declined: set[str] = set()
    pending: set[str] = set()  # предложения из последней реплики менеджера
    client_tokens: list[str] = []

    turns = [(t.role, t.text) for t in dialog]
    if message:
        turns.append(("client", message))

    for role, text in turns:
        mentioned = mentioned_products(kb, text)
        if role == "manager":
            new_offers = {pid for pid in mentioned if pid in offers and pid not in deal}
            deal |= mentioned - new_offers
            offered |= new_offers
            pending = new_offers
            continue

        client_tokens += tokenize(text)
        rejected, accepted = _client_reaction(kb, text, pending)
        declined = (declined | rejected) - accepted
        deal |= {pid for pid in mentioned if pid not in offers} - rejected
        pending = set()

    return DialogFacts(
        deal_product_ids=frozenset(deal),
        offered_product_ids=frozenset(offered),
        declined_product_ids=frozenset(declined),
        client_tokens=tuple(client_tokens),
    )


def _client_reaction(kb: KnowledgeBase, text: str, pending: set[str]) -> tuple[set[str], set[str]]:
    """Возвращает (отклонённые, принятые/интересующие) товары для одной реплики клиента."""
    rejected: set[str] = set()
    accepted: set[str] = set()
    general_refusal = False

    for segment in _segments(text):
        if segment.rstrip().endswith("?"):
            accepted |= mentioned_products(kb, segment)
            continue
        products = mentioned_products(kb, segment)
        if products:
            is_refusal = _PRODUCT_REFUSAL.search(segment) and not _ACCEPTANCE.search(segment)
            (rejected if is_refusal else accepted).update(products)
        elif _GENERAL_REFUSAL.search(segment.strip()):
            general_refusal = True

    # «Нет, спасибо» относится к последним предложениям, только если клиент не назвал товары сам
    if general_refusal and not (rejected or accepted):
        rejected |= pending
    return rejected - accepted, accepted

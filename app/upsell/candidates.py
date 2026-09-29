"""Детерминированные кандидаты на допродажу: правила БЗ × товары сделки × слова клиента (ADR-002).

LLM получает только этот список и может выбрать из него, но не дополнить. Интентные условия
правил (`if_intents_any`, `never_if_intents`) проверяются guardrail-ом после ответа LLM,
когда интент известен.
"""

from app.kb.models import KnowledgeBase
from app.kb.text import contains_phrase, tokenize
from app.upsell.models import DialogFacts, UpsellCandidate


def build_candidates(kb: KnowledgeBase, facts: DialogFacts) -> tuple[UpsellCandidate, ...]:
    deal_tags = {tag for pid in facts.deal_product_ids for tag in kb.product(pid).tags}
    candidates: dict[str, UpsellCandidate] = {}

    for rule in kb.upsell_rules:
        offer = kb.product(rule.offer_id)
        if (
            offer.id in candidates
            or offer.id in facts.declined_product_ids
            or offer.id in facts.deal_product_ids
            or not offer.in_stock
        ):
            continue

        by_tag = bool(deal_tags.intersection(rule.if_product_tags_any))
        by_keyword = any(
            contains_phrase(facts.client_tokens, tokenize(keyword))
            for keyword in rule.if_message_keywords_any
        )
        if not (by_tag or by_keyword):
            continue

        candidates[offer.id] = UpsellCandidate(
            offer_id=offer.id,
            title=offer.title,
            price=offer.price,
            currency=offer.currency,
            rule_id=rule.id,
            why=rule.why,
            if_intents_any=rule.if_intents_any,
            never_if_intents=rule.never_if_intents,
            already_offered=offer.id in facts.offered_product_ids,
        )

    return tuple(candidates.values())

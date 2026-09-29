"""Демо-БЗ: грузится, соблюдает правила kb-edit и находит нужное на запросах из сценариев SPEC."""

from pathlib import Path

import pytest

from app.kb.loader import load_kb
from app.kb.models import KnowledgeBase
from app.kb.retriever import KeywordRetriever

DEMO_KB = Path(__file__).parents[3] / "data" / "kb"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_kb(DEMO_KB)


def test_demo_kb_is_small_enough_for_full_context(kb: KnowledgeBase) -> None:
    assert 15 <= len(kb.entries) + len(kb.upsell_rules) <= 50


def test_faq_has_several_client_phrasings(kb: KnowledgeBase) -> None:
    thin = [f.id for f in kb.faq if len(f.questions) < 3]

    assert not thin, f"меньше 3 формулировок: {thin}"


def test_every_rule_offer_is_sellable(kb: KnowledgeBase) -> None:
    for rule in kb.upsell_rules:
        offer = kb.product(rule.offer_id)
        assert offer.in_stock, rule.id
        assert "complaint" in rule.never_if_intents, rule.id
        assert "refund" in rule.never_if_intents, rule.id


@pytest.mark.parametrize(
    ("query", "expected_top"),
    [
        ("Сколько стоит доставка в Казань?", "faq.delivery_regions"),
        ("можно оплатить при получении?", "faq.payment"),
        ("Сколько стоит X15?", "product.x15"),
        ("а сумку к ноуту можно?", "product.bag"),
        ("хочу вернуть ноутбук", "faq.returns"),
        ("сделаете скидку 10%?", "policy.discount"),
        ("есть рассрочка?", "faq.installment"),
    ],
)
def test_scenario_queries_find_right_entry(
    kb: KnowledgeBase, query: str, expected_top: str
) -> None:
    hits = KeywordRetriever(kb).retrieve(query).hits

    assert hits, query
    assert hits[0].entry.id == expected_top, [(h.entry.id, round(h.score, 2)) for h in hits[:3]]

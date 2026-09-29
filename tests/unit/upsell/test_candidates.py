"""Инвариант 2: кандидатов на допродажу строит код — правила БЗ × товары сделки × слова клиента."""

from typing import Any

from app.kb.models import Intent, KnowledgeBase
from app.kb.text import tokenize
from app.upsell.candidates import build_candidates
from app.upsell.models import DialogFacts


def facts(
    deal: set[str] | None = None,
    offered: set[str] | None = None,
    declined: set[str] | None = None,
    text: str = "",
) -> DialogFacts:
    return DialogFacts(
        deal_product_ids=frozenset(deal or ()),
        offered_product_ids=frozenset(offered or ()),
        declined_product_ids=frozenset(declined or ()),
        client_tokens=tuple(tokenize(text)),
    )


def ids(kb: KnowledgeBase, f: DialogFacts) -> list[str]:
    return [c.offer_id for c in build_candidates(kb, f)]


def test_laptop_in_deal_triggers_tag_rules_in_kb_order(demo_kb: KnowledgeBase) -> None:
    candidates = build_candidates(demo_kb, facts(deal={"product.x15"}))

    assert [c.offer_id for c in candidates] == [
        "product.warranty_plus",
        "product.bag",
        "product.mouse_m3",
        "product.setup_service",
    ]
    warranty = candidates[0]
    assert warranty.rule_id == "rule.laptop_warranty"
    assert warranty.title == "Расширенная гарантия +2 года"
    assert warranty.price == 5990
    assert warranty.why
    assert Intent.COMPLAINT in warranty.never_if_intents
    assert candidates[3].if_intents_any == (Intent.ORDER_INTENT, Intent.DELIVERY_PAYMENT_QUESTION)


def test_declined_offer_is_not_a_candidate(demo_kb: KnowledgeBase) -> None:
    result = ids(demo_kb, facts(deal={"product.x15"}, declined={"product.bag"}))

    assert "product.bag" not in result
    assert "product.warranty_plus" in result


def test_offered_but_not_declined_is_flagged(demo_kb: KnowledgeBase) -> None:
    candidates = build_candidates(demo_kb, facts(deal={"product.x15"}, offered={"product.bag"}))

    flags = {c.offer_id: c.already_offered for c in candidates}
    assert flags["product.bag"] is True
    assert flags["product.warranty_plus"] is False


def test_no_context_no_candidates(demo_kb: KnowledgeBase) -> None:
    assert ids(demo_kb, facts(text="Здравствуйте")) == []


def test_keyword_rules_fire_from_client_words(demo_kb: KnowledgeBase) -> None:
    assert ids(demo_kb, facts(text="нужен для работы с документами")) == ["product.office_suite"]
    assert ids(demo_kb, facts(text="хочу подключить монитор")) == ["product.dock_d7"]


def test_candidate_knows_how_rule_fired(demo_kb: KnowledgeBase) -> None:
    candidates = build_candidates(demo_kb, facts(deal={"product.x15"}, text="нужен монитор"))

    by_keyword = {c.offer_id: c.by_keyword for c in candidates}
    assert by_keyword["product.dock_d7"] is True
    assert by_keyword["product.warranty_plus"] is False


def test_product_already_in_deal_is_not_offered(demo_kb: KnowledgeBase) -> None:
    result = ids(demo_kb, facts(deal={"product.x15", "product.bag"}))

    assert "product.bag" not in result


def test_same_offer_from_two_rules_appears_once(kb_data: dict[str, Any]) -> None:
    rule = dict(kb_data["upsell_rules"][0], id="rule.second")
    kb_data["upsell_rules"].append(rule)
    kb = KnowledgeBase.model_validate(kb_data)

    candidates = build_candidates(kb, facts(deal={"product.x15"}))

    assert [(c.offer_id, c.rule_id) for c in candidates] == [
        ("product.warranty_plus", "rule.laptop_warranty")
    ]


def test_out_of_stock_offer_is_skipped(kb_data: dict[str, Any]) -> None:
    kb_data["products"][1]["in_stock"] = False
    kb = KnowledgeBase.model_validate(kb_data)

    assert ids(kb, facts(deal={"product.x15"})) == []

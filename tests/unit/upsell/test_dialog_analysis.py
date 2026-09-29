"""Инвариант 4 (не повторять отклонённое): что код понимает из истории чата."""

from dataclasses import dataclass

import pytest

from app.kb.models import KnowledgeBase
from app.upsell.dialog_analysis import analyze_dialog, mentioned_products


@dataclass(frozen=True)
class T:
    role: str
    text: str


def client(text: str) -> T:
    return T("client", text)


def manager(text: str) -> T:
    return T("manager", text)


SPEC_DIALOG = [
    client("Здравствуйте, интересует ноутбук X15"),
    manager("Добрый день! X15 в наличии, 89 990 ₽. Могу предложить сумку к нему"),
    client("Сумка не нужна, спасибо"),
]


def test_mentioned_products_by_alias_and_word_form(demo_kb: KnowledgeBase) -> None:
    assert mentioned_products(demo_kb, "А сумку к икс 15 подберёте?") == {
        "product.bag",
        "product.x15",
    }


def test_spec_example(demo_kb: KnowledgeBase) -> None:
    facts = analyze_dialog(
        demo_kb,
        SPEC_DIALOG,
        "Сколько стоит доставка в Казань и можно оплатить при получении?",
        lead_product_ids=["product.x15"],
    )

    assert facts.deal_product_ids == {"product.x15"}
    assert facts.offered_product_ids == {"product.bag"}
    assert facts.declined_product_ids == {"product.bag"}


@pytest.mark.parametrize(
    ("offer", "reply", "declined"),
    [
        ("Могу предложить сумку", "Нет, спасибо", {"product.bag"}),
        ("Могу предложить сумку", "Спасибо, не нужно", {"product.bag"}),
        ("Могу предложить сумку", "откажусь", {"product.bag"}),
        ("Могу предложить сумку", "нет, сумку беру", set()),
        ("Могу предложить сумку", "а сколько она стоит?", set()),
        ("Могу предложить сумку", "а X13 нет в наличии?", set()),
        ("Могу предложить сумку", "рассрочка без переплаты есть?", set()),
        ("Предлагаю мышку и сумку", "мышку не надо, а сумку давайте", {"product.mouse_m3"}),
        ("Предлагаю мышку и сумку", "не, мышку не надо", {"product.mouse_m3"}),
        ("Could I offer you a bag (сумка)?", "No thanks", {"product.bag"}),
    ],
)
def test_reaction_to_offer(
    demo_kb: KnowledgeBase, offer: str, reply: str, declined: set[str]
) -> None:
    dialog = [client("Беру X15"), manager(offer), client(reply)]

    facts = analyze_dialog(demo_kb, dialog, "Когда доставите?", lead_product_ids=[])

    assert facts.declined_product_ids == declined


def test_decline_in_current_message(demo_kb: KnowledgeBase) -> None:
    dialog = [client("Беру X15"), manager("Оформим расширенную гарантию?")]

    facts = analyze_dialog(demo_kb, dialog, "Расширенная гарантия не нужна. Когда доставка?", [])

    assert facts.declined_product_ids == {"product.warranty_plus"}


def test_client_declines_product_without_offer(demo_kb: KnowledgeBase) -> None:
    facts = analyze_dialog(demo_kb, [client("Беру X15, мышь не нужна")], "Когда доставка?", [])

    assert facts.declined_product_ids == {"product.mouse_m3"}


def test_renewed_interest_cancels_decline(demo_kb: KnowledgeBase) -> None:
    facts = analyze_dialog(demo_kb, SPEC_DIALOG, "А всё-таки, сколько стоит сумка?", [])

    assert facts.declined_product_ids == set()


def test_general_no_does_not_decline_the_main_product(demo_kb: KnowledgeBase) -> None:
    dialog = [manager("Добрый день! X15 в наличии, могу добавить мышку"), client("Нет, спасибо")]

    facts = analyze_dialog(demo_kb, dialog, "Когда привезёте?", lead_product_ids=["product.x15"])

    assert facts.declined_product_ids == {"product.mouse_m3"}
    assert "product.x15" in facts.deal_product_ids


def test_client_tokens_include_history_and_message(demo_kb: KnowledgeBase) -> None:
    facts = analyze_dialog(demo_kb, [client("Нужен для работы")], "Доставка?", [])

    assert "работ" in facts.client_tokens
    assert "доставк" in facts.client_tokens


def test_unknown_lead_products_are_ignored(demo_kb: KnowledgeBase) -> None:
    facts = analyze_dialog(demo_kb, [], "Привет", lead_product_ids=["product.unknown"])

    assert facts.deal_product_ids == set()


@pytest.mark.parametrize(
    ("offer", "reply", "declined"),
    [
        ("Могу предложить гарантию +2 года", "Нет, гарантия не нужна", "product.warranty_plus"),
        (
            "Кстати, к X15 можно оформить гарантию ещё на 2 года — ремонт без вопросов.",
            "Спасибо, не надо",
            "product.warranty_plus",
        ),
        (
            "Могу сразу настроить ноутбук и перенести данные",
            "Не нужно, сам настрою",
            "product.setup_service",
        ),
    ],
)
def test_offer_phrased_in_other_word_forms_is_recognized(
    demo_kb: KnowledgeBase, offer: str, reply: str, declined: str
) -> None:
    dialog = [client("Беру X15"), manager(offer), client(reply)]

    facts = analyze_dialog(demo_kb, dialog, "Когда доставка?", lead_product_ids=["product.x15"])

    assert declined in facts.offered_product_ids
    assert facts.declined_product_ids == {declined}


def test_manufacturer_warranty_is_not_an_offer(demo_kb: KnowledgeBase) -> None:
    dialog = [manager("На X15 гарантия производителя 1 год"), client("Нет, спасибо, понял")]

    facts = analyze_dialog(demo_kb, dialog, "Когда доставка?", lead_product_ids=["product.x15"])

    assert facts.declined_product_ids == set()

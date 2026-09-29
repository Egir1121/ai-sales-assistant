"""Критерий M1: битая БЗ → понятная ошибка; ссылочная целостность проверяется при загрузке."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.kb.loader import KBError, load_kb
from tests.helpers import write_kb

Mutation = Callable[[dict[str, Any]], None]


def test_valid_kb_loads(tmp_path: Path, kb_data: dict[str, Any]) -> None:
    kb = load_kb(write_kb(tmp_path, kb_data))

    assert kb.company.fallback_reply
    assert kb.get("product.x15").title == "Ноутбук X15"  # type: ignore[union-attr]
    assert {e.id for e in kb.entries} == {
        "faq.delivery",
        "faq.payment",
        "product.x15",
        "product.warranty_plus",
        "policy.discount",
    }


def test_directory_with_single_yaml_is_accepted(tmp_path: Path, kb_data: dict[str, Any]) -> None:
    write_kb(tmp_path, kb_data)
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "employer.yaml").write_text("не наша схема: [")

    assert load_kb(tmp_path).company.name == "Тест"


def _dup_product(d: dict[str, Any]) -> None:
    d["products"].append(dict(d["products"][0]))


def _unknown_offer(d: dict[str, Any]) -> None:
    d["upsell_rules"][0]["offer_id"] = "product.nope"


def _offer_is_not_product(d: dict[str, Any]) -> None:
    d["upsell_rules"][0]["offer_id"] = "policy.discount"


def _extra_field(d: dict[str, Any]) -> None:
    d["products"][0]["colour"] = "red"


def _bad_prefix(d: dict[str, Any]) -> None:
    d["faq"][0]["id"] = "delivery"


def _no_fallback(d: dict[str, Any]) -> None:
    del d["company"]["fallback_reply"]


def _negative_price(d: dict[str, Any]) -> None:
    d["products"][0]["price"] = -1


def _unknown_tag(d: dict[str, Any]) -> None:
    d["upsell_rules"][0]["if_product_tags_any"] = ["laptp"]


def _rule_without_trigger(d: dict[str, Any]) -> None:
    d["upsell_rules"][0]["if_product_tags_any"] = []


def _unknown_intent(d: dict[str, Any]) -> None:
    d["upsell_rules"][0]["never_if_intents"] = ["complain"]


def _alias_collision(d: dict[str, Any]) -> None:
    d["products"][1]["aliases"] = ["X15"]


def _no_aliases(d: dict[str, Any]) -> None:
    d["products"][0]["aliases"] = []


def _wrong_version(d: dict[str, Any]) -> None:
    d["version"] = 2


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_dup_product, ["дублируется id", "product.x15"]),
        (_unknown_offer, ["rule.laptop_warranty", "product.nope", "не найден"]),
        (_offer_is_not_product, ["rule.laptop_warranty", "policy.discount"]),
        (_extra_field, ["product.x15", "colour"]),
        (_bad_prefix, ["faq[0]", "id", "faq."]),
        (_no_fallback, ["company.fallback_reply"]),
        (_negative_price, ["product.x15", "price"]),
        (_unknown_tag, ["rule.laptop_warranty", "laptp"]),
        (_rule_without_trigger, ["rule.laptop_warranty", "условие"]),
        (_unknown_intent, ["rule.laptop_warranty", "never_if_intents", "complain"]),
        (_alias_collision, ["x15", "product.x15", "product.warranty_plus"]),
        (_no_aliases, ["product.x15", "aliases"]),
        (_wrong_version, ["version"]),
    ],
)
def test_broken_kb_gives_readable_error(
    tmp_path: Path, kb_data: dict[str, Any], mutate: Mutation, expected: list[str]
) -> None:
    mutate(kb_data)
    path = write_kb(tmp_path, kb_data)

    with pytest.raises(KBError) as exc:
        load_kb(path)

    message = str(exc.value)
    assert str(path) in message
    for fragment in expected:
        assert fragment in message, f"нет {fragment!r} в сообщении:\n{message}"


def test_all_errors_are_reported_at_once(tmp_path: Path, kb_data: dict[str, Any]) -> None:
    _unknown_offer(kb_data)
    _dup_product(kb_data)

    with pytest.raises(KBError) as exc:
        load_kb(write_kb(tmp_path, kb_data))

    assert "product.nope" in str(exc.value)
    assert "дублируется id" in str(exc.value)


def test_yaml_syntax_error_points_to_line(tmp_path: Path) -> None:
    path = tmp_path / "kb.yaml"
    path.write_text("version: 1\nfaq:\n  - id: faq.a\n    questions: [доставка\n", encoding="utf-8")

    with pytest.raises(KBError, match=r"kb\.yaml:\d+:\d+"):
        load_kb(path)


@pytest.mark.parametrize(
    ("content", "expected"),
    [("", "пуст"), ("- a\n- b\n", "словарь")],
)
def test_wrong_top_level_shape(tmp_path: Path, content: str, expected: str) -> None:
    path = tmp_path / "kb.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(KBError, match=expected):
        load_kb(path)


def test_missing_path(tmp_path: Path) -> None:
    with pytest.raises(KBError, match="не найден"):
        load_kb(tmp_path / "nope")


def test_directory_must_contain_exactly_one_yaml(tmp_path: Path, kb_data: dict[str, Any]) -> None:
    with pytest.raises(KBError, match="найдено 0"):
        load_kb(tmp_path)

    write_kb(tmp_path, kb_data, "a.yaml")
    write_kb(tmp_path, kb_data, "b.yml")
    with pytest.raises(KBError, match="найдено 2"):
        load_kb(tmp_path)

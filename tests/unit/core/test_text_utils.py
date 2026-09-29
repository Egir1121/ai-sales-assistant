import pytest

from app.core.language import detect_language
from app.core.normalize import MAX_DIALOG_TURNS, MAX_MESSAGE_CHARS, has_content, normalize_text
from app.core.pii import mask_pii
from app.core.signals import negative_signals


def test_normalize_trims_and_truncates() -> None:
    assert normalize_text("  привет \n") == "привет"
    assert len(normalize_text("я" * 5000)) == MAX_MESSAGE_CHARS
    assert MAX_DIALOG_TURNS >= 10


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", False), ("   ", False), ("???", False), ("...!!", False), ("да", True), ("5", True)],
)
def test_has_content(text: str, expected: bool) -> None:
    assert has_content(text) is expected


@pytest.mark.parametrize(
    "raw",
    ["+7 (912) 345-67-89", "8 912 345 67 89", "89123456789", "+44 20 7946 0958", "anna.k@mail.ru"],
)
def test_pii_is_masked(raw: str) -> None:
    masked = mask_pii(f"Мои контакты: {raw}, спасибо")

    assert raw not in masked
    assert "спасибо" in masked


def test_prices_and_dates_are_not_masked() -> None:
    text = "X15 стоит 89 990 ₽, доставка 2–7 дней, заказ 48213"

    assert mask_pii(text) == text


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Сколько стоит доставка?", "ru"),
        ("How much is delivery to Kazan?", "en"),
        ("Hi! Можно X15?", "ru"),
        ("12345", None),
        ("", None),
    ],
)
def test_detect_language(text: str, language: str | None) -> None:
    assert detect_language(text) == language


@pytest.mark.parametrize(
    ("text", "signals"),
    [
        ("Ноутбук сломался через неделю, это ужас", {"complaint"}),
        ("Верните деньги немедленно", {"refund"}),
        ("Хочу оформить возврат", {"refund"}),
        ("Вы обманщики, отвратительный сервис", {"complaint"}),
        ("The laptop is broken, I want a refund", {"complaint", "refund"}),
        ("Как вернуть товар, если не подойдёт?", set()),
        ("Сколько стоит доставка?", set()),
    ],
)
def test_negative_signals(text: str, signals: set[str]) -> None:
    assert negative_signals(text) == signals

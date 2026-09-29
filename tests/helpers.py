"""Общие тестовые данные и хелперы."""

from pathlib import Path
from typing import Any

import yaml

MINIMAL_KB: dict[str, Any] = {
    "version": 1,
    "company": {
        "name": "Тест",
        "tone": "на вы, коротко",
        "signature": "Команда Тест",
        "fallback_reply": "Спасибо! Уточню детали и вернусь с ответом.",
    },
    "faq": [
        {
            "id": "faq.delivery",
            "questions": ["доставка", "сколько везти"],
            "answer": "Доставка по России — 2–7 рабочих дней, 690 ₽.",
        },
        {
            "id": "faq.payment",
            "questions": ["как оплатить", "оплата при получении"],
            "answer": "Оплата картой онлайн или при получении.",
        },
    ],
    "products": [
        {
            "id": "product.x15",
            "title": "Ноутбук X15",
            "price": 89990,
            "tags": ["laptop"],
            "aliases": ["x15", "икс 15"],
        },
        {
            "id": "product.warranty_plus",
            "title": "Расширенная гарантия +2 года",
            "price": 5990,
            "tags": ["service"],
            "aliases": ["расширенная гарантия"],
        },
    ],
    "policies": [
        {"id": "policy.discount", "text": "Скидку больше 5% согласует руководитель отдела продаж."}
    ],
    "upsell_rules": [
        {
            "id": "rule.laptop_warranty",
            "if_product_tags_any": ["laptop"],
            "offer_id": "product.warranty_plus",
            "why": "Снижает страх поломки дорогой покупки",
            "never_if_intents": ["complaint", "refund"],
        }
    ],
}


def write_kb(directory: Path, data: dict[str, Any], name: str = "kb.yaml") -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path

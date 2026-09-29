"""Язык сообщения по доле кириллицы и латиницы — без внешних зависимостей (ADR, A16).

Поддерживаем ru/en: этого достаточно для S9. Название товара латиницей («X15») в русском
предложении не делает его английским: решает большинство букв, при равенстве — ru.
"""

import re

_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)


def detect_language(text: str) -> str | None:
    cyrillic = len(_CYRILLIC.findall(text))
    latin = len(_LATIN.findall(text))
    if not cyrillic and not latin:
        return None
    return "ru" if cyrillic >= latin else "en"

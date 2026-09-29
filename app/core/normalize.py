"""Нормализация входа (SPEC §6.1): trim, ограничение длины сообщения и истории."""

import re

MAX_MESSAGE_CHARS = 2000
MAX_DIALOG_TURNS = 30

_MEANINGFUL = re.compile(r"[^\W_]")


def normalize_text(text: str) -> str:
    return text.strip()[:MAX_MESSAGE_CHARS]


def has_content(text: str) -> bool:
    """Есть ли в тексте хоть одна буква или цифра (S10: пустые и «???» не отправляем в LLM)."""
    return bool(_MEANINGFUL.search(text))

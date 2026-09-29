"""Нормализация текста для поиска по БЗ: нижний регистр, ё→е, без стоп-слов, со стеммингом.

Стемминг — Snowball (ru/en): «доставку», «доставки» → «доставк». Смешанные токены вроде «x15»
и числа не стеммятся.
"""

import re
from collections.abc import Sequence
from functools import lru_cache
from typing import cast

import snowballstemmer

_WORD = re.compile(r"[^\W_]+")
_CYRILLIC = re.compile(r"^[а-я]+$")
_LATIN = re.compile(r"^[a-z]+$")

_STOPWORDS_TEXT = """
а и в во на с со по к ко о об от до из за у же ли бы то но или да ну вот тут там уже еще
я мне меня мы нам нас вы вам вас он она оно они его ее их это этот эта эти тот та как
что где когда какой какая какое какие кто чем чтобы если для при про можно пожалуйста a
an the is are am be to of for and or in on at do does did can could i me you we it this
that please
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())

_ru = snowballstemmer.stemmer("russian")
_en = snowballstemmer.stemmer("english")


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


@lru_cache(maxsize=16384)
def stem(word: str) -> str:
    if _CYRILLIC.match(word):
        return cast(str, _ru.stemWord(word))
    if _LATIN.match(word):
        return cast(str, _en.stemWord(word))
    return word


def tokenize(text: str) -> list[str]:
    """Токены для поиска: нормализованные, без стоп-слов, стеммированные, в исходном порядке."""
    return [stem(w) for w in _WORD.findall(normalize(text)) if w not in STOPWORDS]


def contains_phrase(tokens: Sequence[str], phrase: Sequence[str]) -> bool:
    """Есть ли `phrase` в `tokens` как непрерывная последовательность целых токенов."""
    n = len(phrase)
    if n == 0:
        return False
    return any(list(tokens[i : i + n]) == list(phrase) for i in range(len(tokens) - n + 1))

"""Детерминированные сигналы по тексту клиента — независимые от классификации LLM.

- `negative_signals`: жалоба/раздражение/грубость и требование возврата → подавление допродажи
  (инвариант 3, допущение A14). Нейтральные вопросы о правилах возврата сигналом не считаются.
- `injection_signal`: попытка переписать инструкции ассистента (инвариант 5).
- `is_gibberish`: набор символов без единого знакомого слова → уточняющий вопрос без LLM (S10).
"""

import re
from typing import Literal

from app.kb.text import ROOT_LEN, STOPWORDS, normalize, root, stem

Signal = Literal["complaint", "refund"]

_COMPLAINT = re.compile(
    # поломка и качество
    r"сломал|не работает|не включается|брак|"
    # оценка сервиса и эмоции
    r"ужас|кошмар|отвратительн|безобраз|обман|жалоб|претензи|разочарован|хамств|возмутительн|"
    r"позор|издевае|надоел|достал[иао]?\b|бесит|бесите|"
    # оскорбления
    r"идиот|дебил|придур|тупые|кретин|"
    # долгое ожидание
    r"сколько можно|до сих пор нет|никто не (отвечает|звонит|перезвонил)|где мой заказ|"
    r"жд[уеё]\w*\s+(уже\s+)?(\S+\s+)?(дн|недел|месяц)|"
    # английский
    r"\bbroken\b|\bterrible\b|\bawful\b|\bcomplain|\bscam\b|\bdisgusting\b|\bridiculous\b|"
    r"\bidiots?\b|\bstupid\b|still waiting|where is my order|"
    # многократные ! и ?
    r"[!?]{3,}",
    re.IGNORECASE,
)
_REFUND = re.compile(
    r"верните\s+деньги|вернуть\s+деньги|хочу\s+вернуть|оформить\s+возврат|требую\s+возврат|"
    r"деньги\s+назад|\brefund\b|\bmoney back\b",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"игнорир\w*\s+(все\s+|всё\s+)?(предыдущ\w+\s+)?(инструкц|правил|указан)|"
    r"забудь\s+(все\s+|всё\s+)?(инструкц|правил)|ты\s+теперь\b|"
    r"(систем\w*|свой|твой)\s+промпт|system prompt|"
    r"ignore\s+(all\s+)?(previous\s+|prior\s+)?(instructions|rules)|you are now\b",
    re.IGNORECASE,
)

# Слова, которыми клиенты открывают любой вопрос, даже если темы нет в БЗ.
_CLIENT_WORDS = """
здравствуйте привет добрый день вечер утро спасибо благодарю подскажите скажите интересует
интересно хочу хотел хотела узнать уточнить вопрос нужен нужна нужно надо купить заказать
заказ беру возьму сколько стоит почём почем цена есть продаете продаёте можно возможно ок окей
сегодня завтра сейчас быстро срочно тоже также вообще просто очень ещё еще уже сам сама самому
ли какой какая какие когда где как
hello hi hey thanks thank price cost how much what when where why have want need buy order
yes no ok okay
"""
CLIENT_STEMS = frozenset(stem(w) for w in normalize(_CLIENT_WORDS).split())

_WORD = re.compile(r"[^\W_]+")
_MIN_KNOWN_SHARE = 0.15


def negative_signals(text: str) -> set[Signal]:
    signals: set[Signal] = set()
    if _COMPLAINT.search(text):
        signals.add("complaint")
    if _REFUND.search(text):
        signals.add("refund")
    return signals


def injection_signal(text: str) -> bool:
    return bool(_INJECTION.search(text))


def is_gibberish(text: str, vocabulary: frozenset[str]) -> bool:
    """Нет ни одного знакомого слова (служебного, типового для клиента или из БЗ) — или их
    почти нет в длинном тексте. Числа считаются осмысленными."""
    words = _WORD.findall(normalize(text))
    if not words:
        return False
    known = sum(1 for w in words if _is_known(w, vocabulary))
    if known == 0:
        return True
    return len(words) >= 20 and known / len(words) < _MIN_KNOWN_SHARE


def _is_known(word: str, vocabulary: frozenset[str]) -> bool:
    if word.isdigit() or (len(word) >= 2 and word in STOPWORDS):
        return True
    s = stem(word)
    if s in CLIENT_STEMS or s in vocabulary:
        return True
    return len(s) > ROOT_LEN and f"~{root(s)}" in vocabulary

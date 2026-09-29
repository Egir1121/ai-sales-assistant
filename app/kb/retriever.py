"""Retrieval по БЗ (ADR-001).

`Retriever.retrieve(query)` возвращает:
- `context` — записи, которые пойдут в промпт (стабильный порядок → кэшируемый префикс);
- `hits` — релевантные записи по убыванию score (для kb_refs в FakeLLM, отладки и evals).

`FullContextRetriever` кладёт в промпт всю БЗ, `KeywordRetriever` — top-k + все политики.
`make_retriever(kb, "auto")` выбирает режим по размеру БЗ.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.kb.models import FaqEntry, KBEntry, KnowledgeBase, Policy, Product
from app.kb.text import contains_phrase, tokenize

RetrieverMode = Literal["auto", "full", "keyword"]

# Порог переключения auto → keyword. Грубая оценка токенов: ~3 символа на токен для русского текста.
MAX_FULL_CONTEXT_ENTRIES = 200
MAX_FULL_CONTEXT_TOKENS = 30_000
_CHARS_PER_TOKEN = 3

# Прямое упоминание товара по алиасу («икс 15») важнее совпадения отдельных слов.
ALIAS_BONUS = 10.0

# Snowball разводит формы одного корня («доставить» → «достав», «доставка» → «доставк»).
# Поэтому индексируем ещё и префикс основы — с половинным весом, чтобы точное совпадение
# оставалось сильнее и случайные совпадения корней не выходили в топ.
PREFIX_LEN = 5
PREFIX_WEIGHT = 0.5


def index_terms(tokens: Sequence[str]) -> list[str]:
    return [*tokens, *(f"~{t[:PREFIX_LEN]}" for t in tokens if len(t) > PREFIX_LEN)]


def _weight(term: str) -> float:
    return PREFIX_WEIGHT if term.startswith("~") else 1.0


@dataclass(frozen=True)
class KBHit:
    entry: KBEntry
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    context: tuple[KBEntry, ...]
    hits: tuple[KBHit, ...]


class Retriever(Protocol):
    def retrieve(self, query: str) -> RetrievalResult: ...


def entry_text(entry: KBEntry) -> str:
    match entry:
        case FaqEntry():
            return " ".join([*entry.questions, entry.answer])
        case Product():
            return " ".join([entry.title, *entry.aliases, *entry.tags, entry.description])
        case Policy():
            return entry.text


class _BM25:
    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._tf = [Counter(doc) for doc in docs]
        self._len = [len(doc) for doc in docs]
        self._avg_len = (sum(self._len) / len(docs)) if docs else 0.0
        self._df = Counter(term for doc in docs for term in set(doc))
        self._n = len(docs)

    def scores(self, query: Sequence[str]) -> list[float]:
        result = [0.0] * self._n
        for term in set(query):
            df = self._df.get(term, 0)
            if not df:
                continue
            idf = _weight(term) * math.log(1 + (self._n - df + 0.5) / (df + 0.5))
            for i, tf in enumerate(self._tf):
                freq = tf.get(term, 0)
                if freq:
                    norm = 1 - self._b + self._b * self._len[i] / self._avg_len
                    result[i] += idf * freq * (self._k1 + 1) / (freq + self._k1 * norm)
        return result


class KeywordRetriever:
    """BM25 по токенам записей + бонус за прямое упоминание товара по алиасу."""

    def __init__(self, kb: KnowledgeBase, k: int = 5) -> None:
        self._kb = kb
        self._k = k
        self._entries = kb.entries
        self._bm25 = _BM25([index_terms(tokenize(entry_text(e))) for e in self._entries])
        self._aliases = [
            [tokenize(a) for a in e.aliases] if isinstance(e, Product) else []
            for e in self._entries
        ]

    def rank(self, query: str) -> tuple[KBHit, ...]:
        tokens = tokenize(query)
        if not tokens:
            return ()
        scores = self._bm25.scores(index_terms(tokens))
        for i, aliases in enumerate(self._aliases):
            if any(contains_phrase(tokens, alias) for alias in aliases):
                scores[i] += ALIAS_BONUS
        ranked = sorted(
            (KBHit(e, s) for e, s in zip(self._entries, scores, strict=True) if s > 0),
            key=lambda hit: hit.score,
            reverse=True,
        )
        return tuple(ranked[: self._k])

    def retrieve(self, query: str) -> RetrievalResult:
        hits = self.rank(query)
        top = [hit.entry for hit in hits]
        policies = [p for p in self._kb.policies if p not in top]
        return RetrievalResult(context=(*top, *policies), hits=hits)


class FullContextRetriever:
    """Вся БЗ в промпт (один и тот же кортеж на каждый запрос); ранжирование — через BM25."""

    def __init__(self, kb: KnowledgeBase, k: int = 5) -> None:
        self._context = kb.entries
        self._ranker = KeywordRetriever(kb, k=k)

    def retrieve(self, query: str) -> RetrievalResult:
        return RetrievalResult(context=self._context, hits=self._ranker.rank(query))


def estimate_tokens(kb: KnowledgeBase) -> int:
    return sum(len(entry_text(e)) for e in kb.entries) // _CHARS_PER_TOKEN


def make_retriever(kb: KnowledgeBase, mode: RetrieverMode = "auto") -> Retriever:
    if mode == "auto":
        small = (
            len(kb.entries) <= MAX_FULL_CONTEXT_ENTRIES
            and estimate_tokens(kb) <= MAX_FULL_CONTEXT_TOKENS
        )
        mode = "full" if small else "keyword"
    return FullContextRetriever(kb) if mode == "full" else KeywordRetriever(kb)

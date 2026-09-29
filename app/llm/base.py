"""Контракт LLM-провайдера. Пайплайн знает только `LLMClient` — реализация подменяется через DI."""

from dataclasses import dataclass
from typing import Protocol

from app.kb.models import KnowledgeBase
from app.kb.retriever import RetrievalResult
from app.llm.schema import LLMOutput
from app.upsell.models import DialogFacts, Turn, UpsellCandidate


class LLMError(Exception):
    """Провайдер недоступен или вернул непригодный ответ → пайплайн уходит в фолбэк."""


@dataclass(frozen=True)
class PromptContext:
    """Структурированные входные данные запроса. FakeLLM работает с ними, а не парсит текст."""

    kb: KnowledgeBase
    retrieval: RetrievalResult
    candidates: tuple[UpsellCandidate, ...]
    facts: DialogFacts
    dialog: tuple[Turn, ...]
    message: str
    client_name: str | None
    stage: str | None


@dataclass(frozen=True)
class LLMRequest:
    system: str
    kb_block: str
    """<knowledge_base> — стабильный префикс, кэшируется провайдером."""
    dynamic_block: str
    """<upsell_candidates>, <declined>, <lead>, <dialog>, <client_message> — на каждый запрос."""
    context: PromptContext


@dataclass(frozen=True)
class LLMResult:
    output: LLMOutput
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


class LLMClient(Protocol):
    provider: str
    model: str

    async def generate(self, request: LLMRequest) -> LLMResult: ...

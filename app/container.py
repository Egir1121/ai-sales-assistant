"""Сборка зависимостей из Settings — общая для HTTP-приложения и CLI."""

from dataclasses import dataclass

from app.config import Settings
from app.core.pipeline import AssistService
from app.kb.loader import load_kb
from app.kb.models import KnowledgeBase
from app.kb.retriever import Retriever, make_retriever
from app.llm.base import LLMClient
from app.llm.fake import FakeLLM


@dataclass(frozen=True)
class Container:
    kb: KnowledgeBase
    retriever: Retriever
    llm: LLMClient
    assist: AssistService


def make_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLM()
    from app.llm.anthropic_client import AnthropicLLMClient  # SDK грузим, только если нужен

    assert settings.anthropic_api_key is not None  # гарантирует валидация Settings
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout_s=settings.llm_timeout_s,
        effort=settings.llm_effort,
    )


def build_container(settings: Settings) -> Container:
    kb = load_kb(settings.kb_path)  # битая БЗ → KBError, сервис не стартует
    retriever = make_retriever(kb, settings.kb_retriever)
    llm = make_llm_client(settings)
    return Container(
        kb=kb,
        retriever=retriever,
        llm=llm,
        assist=AssistService(kb, retriever, llm, timeout_s=settings.llm_timeout_s),
    )

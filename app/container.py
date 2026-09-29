"""Сборка зависимостей из Settings — общая для HTTP-приложения и CLI."""

from dataclasses import dataclass

from app.config import Settings
from app.core.pipeline import AssistService
from app.integrations.amocrm.dialog_store import InMemoryDialogStore
from app.integrations.amocrm.notes import LiveNotesClient, MockNotesClient, NotesClient
from app.integrations.amocrm.processor import WebhookProcessor
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
    amocrm: WebhookProcessor


def make_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLM()
    from app.llm.anthropic_client import AnthropicLLMClient  # SDK грузим, только если нужен

    if settings.anthropic_api_key is None:  # Settings это уже проверяет; здесь — для типов и -O
        raise ValueError("LLM_PROVIDER=anthropic требует ANTHROPIC_API_KEY")
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout_s=settings.llm_timeout_s,
        effort=settings.llm_effort,
    )


def make_notes_client(settings: Settings) -> NotesClient:
    if settings.amocrm_mode == "mock":
        return MockNotesClient()
    if not (settings.amocrm_subdomain and settings.amocrm_access_token):
        raise ValueError("AMOCRM_MODE=live требует AMOCRM_SUBDOMAIN и AMOCRM_ACCESS_TOKEN")
    return LiveNotesClient(
        subdomain=settings.amocrm_subdomain,
        access_token=settings.amocrm_access_token.get_secret_value(),
    )


def build_container(settings: Settings) -> Container:
    kb = load_kb(settings.kb_path)  # битая БЗ → KBError, сервис не стартует
    retriever = make_retriever(kb, settings.kb_retriever)
    llm = make_llm_client(settings)
    assist = AssistService(kb, retriever, llm, timeout_s=settings.llm_timeout_s)
    return Container(
        kb=kb,
        retriever=retriever,
        llm=llm,
        assist=assist,
        amocrm=WebhookProcessor(assist, InMemoryDialogStore(), make_notes_client(settings)),
    )

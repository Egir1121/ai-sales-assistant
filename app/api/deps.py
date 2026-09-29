"""Провайдеры зависимостей для FastAPI `Depends`.

Всё собирается в `create_app` и лежит в `app.state`; в тестах подменяется через
`app.dependency_overrides`.
"""

from fastapi import Request

from app.config import Settings
from app.core.pipeline import AssistService
from app.kb.models import KnowledgeBase


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_assist_service(request: Request) -> AssistService:
    service: AssistService = request.app.state.assist
    return service


def get_kb(request: Request) -> KnowledgeBase:
    kb: KnowledgeBase = request.app.state.kb
    return kb

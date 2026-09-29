"""Провайдеры зависимостей для FastAPI `Depends`.

Всё собирается в `create_app` и лежит в `app.state`.
"""

from fastapi import Request

from app.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings

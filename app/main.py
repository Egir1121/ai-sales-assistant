"""HTTP-приложение: собирает зависимости из Settings (см. app/container.py).

Запуск через фабрику, чтобы импорт модуля не загружал БЗ и не читал .env побочным эффектом:
`uvicorn app.main:create_app --factory`.
"""

import logging

from fastapi import FastAPI

from app import __version__
from app.api import routes_assist, routes_health
from app.api.routes_ui import mount_ui
from app.config import Settings
from app.container import build_container

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    container = build_container(settings)
    logger.info(
        "БЗ загружена: %d записей, %d правил допродажи; retriever=%s, llm=%s/%s",
        len(container.kb.entries),
        len(container.kb.upsell_rules),
        settings.kb_retriever,
        container.llm.provider,
        container.llm.model,
    )

    app = FastAPI(title="AI Sales Assistant", version=__version__)
    app.state.settings = settings
    app.state.kb = container.kb
    app.state.retriever = container.retriever
    app.state.assist = container.assist
    app.include_router(routes_health.router)
    app.include_router(routes_assist.router)
    mount_ui(app)
    return app

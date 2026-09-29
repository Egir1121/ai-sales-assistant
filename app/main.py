"""Composition root: собирает приложение и его зависимости из Settings."""

import logging

from fastapi import FastAPI

from app import __version__
from app.api import routes_health
from app.config import Settings
from app.kb.loader import load_kb
from app.kb.retriever import make_retriever

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    kb = load_kb(settings.kb_path)  # битая БЗ → KBError, сервис не стартует
    logger.info(
        "БЗ загружена: %d записей, %d правил допродажи, retriever=%s",
        len(kb.entries),
        len(kb.upsell_rules),
        settings.kb_retriever,
    )

    app = FastAPI(title="AI Sales Assistant", version=__version__)
    app.state.settings = settings
    app.state.kb = kb
    app.state.retriever = make_retriever(kb, settings.kb_retriever)
    app.include_router(routes_health.router)
    return app


app = create_app()

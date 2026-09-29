"""Composition root: собирает приложение и его зависимости из Settings."""

import logging

from fastapi import FastAPI

from app import __version__
from app.api import routes_health
from app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    app = FastAPI(title="AI Sales Assistant", version=__version__)
    app.state.settings = settings
    app.include_router(routes_health.router)
    return app


app = create_app()

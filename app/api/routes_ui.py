"""Демо-UI «карточка сделки»: статическая страница без сборки и CDN (работает офлайн)."""

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UI_DIR = Path(__file__).parent / "ui"

router = APIRouter(include_in_schema=False)


@router.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


def mount_ui(app: FastAPI) -> None:
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import __version__
from app.api.deps import get_settings
from app.config import Settings

router = APIRouter(tags=["service"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    llm_provider: str


@router.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(version=__version__, llm_provider=settings.llm_provider)

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_assist_service, get_kb
from app.core.models import AssistRequest, AssistResponse
from app.core.pipeline import AssistService
from app.kb.models import KnowledgeBase

router = APIRouter(prefix="/v1", tags=["assist"])


@router.post("/assist")
async def assist(
    request: AssistRequest, service: Annotated[AssistService, Depends(get_assist_service)]
) -> AssistResponse:
    """Черновик ответа клиенту по БЗ + подсказка менеджеру по допродаже (SPEC §4)."""
    return await service.assist(request)


class ProductSummary(BaseModel):
    id: str
    title: str
    price: int
    currency: str
    tags: list[str]


@router.get("/kb/products")
def kb_products(kb: Annotated[KnowledgeBase, Depends(get_kb)]) -> list[ProductSummary]:
    """Товары БЗ — для выбора товаров сделки в демо-UI."""
    return [
        ProductSummary(
            id=p.id, title=p.title, price=p.price, currency=p.currency, tags=list(p.tags)
        )
        for p in kb.products
    ]

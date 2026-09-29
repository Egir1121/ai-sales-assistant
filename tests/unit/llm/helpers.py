from dataclasses import dataclass

from app.kb.models import KnowledgeBase
from app.kb.retriever import FullContextRetriever
from app.llm.base import PromptContext
from app.upsell.candidates import build_candidates
from app.upsell.dialog_analysis import analyze_dialog


@dataclass(frozen=True)
class Turn:
    role: str
    text: str


def make_context(
    kb: KnowledgeBase,
    message: str,
    dialog: tuple[Turn, ...] = (),
    lead_product_ids: tuple[str, ...] = (),
    client_name: str | None = None,
) -> PromptContext:
    facts = analyze_dialog(kb, dialog, message, lead_product_ids)
    return PromptContext(
        kb=kb,
        retrieval=FullContextRetriever(kb).retrieve(message),
        candidates=build_candidates(kb, facts),
        facts=facts,
        dialog=dialog,
        message=message,
        client_name=client_name,
        stage=None,
    )

"""Контракт `POST /v1/assist` (SPEC §4). Ответ собирает код после guardrails, а не LLM напрямую."""

from typing import Literal

from pydantic import BaseModel, Field

from app.kb.models import Intent, Sentiment

# Мягкие верхние границы: защищают от злоупотреблений, но не отвергают длинный текст —
# сообщение обрезается до MAX_MESSAGE_CHARS в пайплайне (SPEC §6.1).
_MAX_TEXT = 20_000
_MAX_TURNS = 500


class DialogTurn(BaseModel):
    role: Literal["client", "manager"]
    text: str = Field(max_length=_MAX_TEXT)


class Lead(BaseModel):
    id: int | None = None
    stage: str | None = Field(default=None, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    product_ids: list[str] = Field(default_factory=list, max_length=50)


class AssistRequest(BaseModel):
    message: str = Field(max_length=_MAX_TEXT)
    dialog: list[DialogTurn] = Field(default_factory=list, max_length=_MAX_TURNS)
    lead: Lead = Field(default_factory=Lead)


class ClientReply(BaseModel):
    text: str
    language: str
    kb_refs: list[str]
    needs_manager: bool


class UpsellOffer(BaseModel):
    offer_id: str
    title: str
    why: str
    pitch: str
    when_to_say: str
    confidence: float = Field(ge=0, le=1)


class ManagerHint(BaseModel):
    summary: str
    intent: Intent
    sentiment: Sentiment
    upsell: list[UpsellOffer]
    upsell_suppressed_reason: str | None
    declined_offer_ids: list[str]
    next_best_action: str
    risk_flags: list[str]


class Meta(BaseModel):
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float | None = None
    fallback_used: bool
    guardrails_applied: list[str] = Field(default_factory=list)


class AssistResponse(BaseModel):
    request_id: str
    client_reply: ClientReply
    manager_hint: ManagerHint
    meta: Meta

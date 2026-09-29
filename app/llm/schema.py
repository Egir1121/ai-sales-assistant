"""Схема ответа LLM (structured output). Это не HTTP-контракт: title/why допродажи, язык и
итоговые флаги достраивает код после guardrails (`app/core/pipeline.py`).

Изменение схемы → навык /prompt-change: модель, guardrails и тесты — в одном коммите.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.kb.models import Intent, Sentiment


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMUpsell(_Strict):
    offer_id: str = Field(description="offer_id строго из <upsell_candidates>")
    reason: str = Field(description="Почему уместно именно сейчас, по контексту диалога (1 фраза)")
    pitch: str = Field(description="Готовая фраза менеджера клиенту, на языке клиента")
    when_to_say: str = Field(description="В какой момент диалога сказать")
    confidence: float = Field(ge=0, le=1, description="Уверенность в уместности, 0..1")


class LLMOutput(_Strict):
    language: str = Field(description="Язык сообщения клиента, ISO 639-1 (ru, en, …)")
    intent: Intent
    sentiment: Sentiment
    client_reply: str = Field(
        description="Черновик ответа клиенту на его языке, только факты из БЗ"
    )
    kb_refs: list[str] = Field(description="id записей БЗ, на которых основан ответ")
    needs_manager: bool = Field(
        description="true, если в БЗ нет данных для ответа или нужно согласование"
    )
    summary: str = Field(
        description="Сводка для менеджера по-русски: что хочет клиент, что уже было"
    )
    upsell: list[LLMUpsell] = Field(description="0–2 предложения из <upsell_candidates>")
    declined_offer_ids: list[str] = Field(
        description="id товаров, от которых клиент отказался в диалоге"
    )
    next_best_action: str = Field(description="Следующий шаг менеджера, по-русски")
    risk_flags: list[str] = Field(description="Риски: discount_request, needs_approval и т.п.")

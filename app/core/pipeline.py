"""AssistService — оркестрация пайплайна (SPEC §6).

нормализация → анализ диалога → кандидаты → retrieval → один вызов LLM (с дедлайном)
→ guardrails → сборка ответа. Ошибка или таймаут LLM → шаблонный фолбэк (инвариант 7).
"""

import asyncio
import logging
import time
import uuid
from typing import NamedTuple

from app.core.guardrails import Draft, GuardrailContext, apply_guardrails
from app.core.language import detect_language
from app.core.models import (
    AssistRequest,
    AssistResponse,
    ClientReply,
    DialogTurn,
    ManagerHint,
    Meta,
    UpsellOffer,
)
from app.core.normalize import MAX_DIALOG_TURNS, has_content, normalize_text
from app.core.pii import mask_pii
from app.core.signals import is_gibberish
from app.kb.models import Intent, KnowledgeBase
from app.kb.retriever import Retriever
from app.llm.base import LLMClient, LLMError, LLMResult, PromptContext
from app.llm.prompts import PROMPT_VERSION, build_request
from app.upsell.candidates import build_candidates
from app.upsell.dialog_analysis import analyze_dialog
from app.upsell.models import DialogFacts, UpsellCandidate

logger = logging.getLogger(__name__)

CLARIFY_REPLY = {
    "ru": "Здравствуйте! Уточните, пожалуйста, что вас интересует?",
    "en": "Hello! Could you please clarify what you are interested in?",
}
# fallback_reply в БЗ — на языке компании; для остальных языков нейтральный шаблон без фактов
FALLBACK_REPLY_EN = (
    "Hello! Thank you for your message. We will check the details and get back to you shortly."
)


class Prepared(NamedTuple):
    message: str
    dialog: tuple[DialogTurn, ...]
    facts: DialogFacts
    candidates: tuple[UpsellCandidate, ...]


class AssistService:
    def __init__(
        self, kb: KnowledgeBase, retriever: Retriever, llm: LLMClient, timeout_s: float
    ) -> None:
        self._kb = kb
        self._retriever = retriever
        self._llm = llm
        self._timeout_s = timeout_s

    def prepare(self, request: AssistRequest) -> Prepared:
        """Детерминированная часть до LLM: нормализация, анализ диалога, кандидаты допродажи."""
        message = normalize_text(request.message)
        dialog = tuple(
            DialogTurn(role=t.role, text=normalize_text(t.text))
            for t in request.dialog[-MAX_DIALOG_TURNS:]
        )
        facts = analyze_dialog(self._kb, dialog, message, request.lead.product_ids)
        return Prepared(message, dialog, facts, build_candidates(self._kb, facts))

    async def assist(self, request: AssistRequest) -> AssistResponse:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        message, dialog, facts, candidates = self.prepare(request)
        logger.info(
            "assist request_id=%s message=%r turns=%d candidates=%s declined=%s",
            request_id,
            mask_pii(message[:200]),
            len(dialog),
            [c.offer_id for c in candidates],
            sorted(facts.declined_product_ids),
        )

        if not has_content(message) or is_gibberish(message, self._kb.vocabulary):
            return self._clarify(request_id, request, facts, started)

        ctx = PromptContext(
            kb=self._kb,
            retrieval=self._retriever.retrieve(message),
            candidates=candidates,
            facts=facts,
            dialog=dialog,
            message=message,
            client_name=request.lead.client_name,
            stage=request.lead.stage,
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                result = await self._llm.generate(build_request(ctx))
        except (TimeoutError, LLMError) as exc:
            logger.warning("LLM недоступен, фолбэк request_id=%s: %r", request_id, exc)
            return self._fallback(request_id, message, facts, started)
        except Exception:  # инвариант 7: любая ошибка провайдера — деградация, а не 500
            logger.exception("Неожиданная ошибка LLM, фолбэк request_id=%s", request_id)
            return self._fallback(request_id, message, facts, started)

        return self._finalize(request_id, ctx, result, started)

    def _finalize(
        self, request_id: str, ctx: PromptContext, result: LLMResult, started: float
    ) -> AssistResponse:
        out = result.output
        declined_by_code = ctx.facts.declined_product_ids
        declined_by_llm = {
            pid for pid in out.declined_offer_ids if pid in self._kb.product_mentions
        }
        draft = Draft(
            reply_text=out.client_reply.strip() or self._kb.company.fallback_reply,
            kb_refs=list(out.kb_refs),
            needs_manager=out.needs_manager or not out.client_reply.strip(),
            intent=out.intent,
            sentiment=out.sentiment,
            summary=out.summary,
            upsell=list(out.upsell),
            upsell_suppressed_reason=None,
            declined_offer_ids=sorted(declined_by_code | declined_by_llm),
            next_best_action=out.next_best_action,
            risk_flags=list(dict.fromkeys(out.risk_flags)),
        )
        applied = apply_guardrails(
            draft,
            GuardrailContext(
                kb=self._kb,
                candidates=ctx.candidates,
                declined_offer_ids=declined_by_code,
                message=ctx.message,
                source_texts=(*(t.text for t in ctx.dialog), ctx.message),
            ),
        )

        language = detect_language(draft.reply_text) or out.language
        if language != (detect_language(ctx.message) or language):
            draft.flag("language_mismatch")
        candidates = {c.offer_id: c for c in ctx.candidates}
        response = AssistResponse(
            request_id=request_id,
            client_reply=ClientReply(
                text=draft.reply_text,
                language=language,
                kb_refs=draft.kb_refs,
                needs_manager=draft.needs_manager,
            ),
            manager_hint=ManagerHint(
                summary=draft.summary,
                intent=draft.intent,
                sentiment=draft.sentiment,
                upsell=[
                    _offer(candidates[o.offer_id], o.reason, o.pitch, o.when_to_say, o.confidence)
                    for o in draft.upsell
                ],
                upsell_suppressed_reason=draft.upsell_suppressed_reason,
                declined_offer_ids=draft.declined_offer_ids,
                next_best_action=draft.next_best_action,
                risk_flags=draft.risk_flags,
            ),
            meta=Meta(
                provider=result.provider,
                model=result.model,
                prompt_version=PROMPT_VERSION,
                latency_ms=_elapsed_ms(started),
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                fallback_used=False,
                guardrails_applied=applied,
            ),
        )
        logger.info(
            "assist done request_id=%s intent=%s upsell=%s guardrails=%s latency_ms=%d "
            "tokens_in=%d tokens_out=%d cost_usd=%s",
            request_id,
            draft.intent,
            [o.offer_id for o in draft.upsell],
            applied,
            response.meta.latency_ms,
            result.tokens_in,
            result.tokens_out,
            result.cost_usd,
        )
        return response

    def _clarify(
        self, request_id: str, request: AssistRequest, facts: DialogFacts, started: float
    ) -> AssistResponse:
        """S10: пустое сообщение или набор символов — уточняющий вопрос без вызова LLM."""
        history = " ".join(t.text for t in request.dialog if t.role == "client")
        language = detect_language(history) or "ru"
        return self._template_response(
            request_id,
            started,
            text=CLARIFY_REPLY.get(language, CLARIFY_REPLY["ru"]),
            language=language,
            needs_manager=False,
            summary="Пустое или непонятное сообщение — нужно уточнение.",
            intent=Intent.UNCLEAR,
            suppressed="Запрос непонятен: сначала уточнить, что нужно клиенту",
            facts=facts,
            risk_flags=[],
            provider="rules",
            fallback=False,
        )

    def _fallback(
        self, request_id: str, message: str, facts: DialogFacts, started: float
    ) -> AssistResponse:
        language = detect_language(message) or "ru"
        return self._template_response(
            request_id,
            started,
            text=self._kb.company.fallback_reply if language == "ru" else FALLBACK_REPLY_EN,
            language=language,
            needs_manager=True,
            summary="LLM недоступен, ответьте вручную.",
            intent=Intent.OTHER,
            suppressed="LLM недоступен: допродажу не подбирали",
            facts=facts,
            risk_flags=["llm_unavailable"],
            provider=self._llm.provider,
            fallback=True,
        )

    def _template_response(
        self,
        request_id: str,
        started: float,
        *,
        text: str,
        language: str,
        needs_manager: bool,
        summary: str,
        intent: Intent,
        suppressed: str,
        facts: DialogFacts,
        risk_flags: list[str],
        provider: str,
        fallback: bool,
    ) -> AssistResponse:
        return AssistResponse(
            request_id=request_id,
            client_reply=ClientReply(
                text=text, language=language, kb_refs=[], needs_manager=needs_manager
            ),
            manager_hint=ManagerHint(
                summary=summary,
                intent=intent,
                sentiment="neutral",
                upsell=[],
                upsell_suppressed_reason=suppressed,
                declined_offer_ids=sorted(facts.declined_product_ids),
                next_best_action="Ответить клиенту вручную" if fallback else "Дождаться уточнения",
                risk_flags=risk_flags,
            ),
            meta=Meta(
                provider=provider,
                model=self._llm.model if fallback else "-",
                prompt_version=PROMPT_VERSION,
                latency_ms=_elapsed_ms(started),
                tokens_in=0,
                tokens_out=0,
                fallback_used=fallback,
            ),
        )


def _offer(
    candidate: UpsellCandidate, reason: str, pitch: str, when: str, confidence: float
) -> UpsellOffer:
    """title и основание берём из кандидата (т.е. из БЗ), от LLM — только формулировки."""
    why = f"Правило {candidate.rule_id}: {candidate.why}"
    if reason.strip():
        why += f"; {reason.strip()}"
    return UpsellOffer(
        offer_id=candidate.offer_id,
        title=candidate.title,
        why=why,
        pitch=pitch,
        when_to_say=when,
        confidence=confidence,
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)

"""Метрики SPEC §9.

Каждая — функция `CaseResult -> bool | None` (None — метрика к кейсу неприменима).

Жёсткие метрики гарантирует код (guardrails), поэтому на любом провайдере ожидаем 100%.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.core.language import detect_language
from app.core.models import AssistResponse
from app.kb.models import KnowledgeBase
from evals.cases import EvalCase

MetricKind = Literal["жёсткая", "мягкая", "инфо"]
HARD: MetricKind = "жёсткая"
SOFT: MetricKind = "мягкая"
INFO: MetricKind = "инфо"


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    response: AssistResponse | None
    candidates: tuple[str, ...]
    """offer_id кандидатов, которые построил код для этого запроса."""
    kb: KnowledgeBase
    error: str | None = None


@dataclass(frozen=True)
class MetricResult:
    name: str
    kind: MetricKind
    value: float | None
    threshold: float | None
    applicable: int
    failed_cases: list[str] = field(default_factory=list)


# --- жёсткие -----------------------------------------------------------------


def schema_valid(r: CaseResult) -> bool:
    """Ответ собран и валиден, LLM не ушёл в фолбэк (фолбэк = LLM не дал валидного ответа)."""
    if r.response is None:
        return False
    AssistResponse.model_validate(r.response.model_dump())
    return not r.response.meta.fallback_used


def kb_refs_valid(r: CaseResult) -> bool | None:
    if r.response is None:
        return None
    return all(r.kb.get(ref) is not None for ref in r.response.client_reply.kb_refs)


def offers_within_candidates(r: CaseResult) -> bool | None:
    if r.response is None:
        return None
    return all(o.offer_id in r.candidates for o in r.response.manager_hint.upsell)


def upsell_suppressed(r: CaseResult) -> bool | None:
    """S4: жалоба/возврат/негатив → upsell пустой и причина заполнена."""
    if r.case.scenario != "S4" or r.response is None:
        return None
    hint = r.response.manager_hint
    return not hint.upsell and bool(hint.upsell_suppressed_reason)


def declined_not_offered(r: CaseResult) -> bool | None:
    """S7: отклонённое распознано и не предлагается снова."""
    if r.case.scenario != "S7" or r.response is None:
        return None
    hint = r.response.manager_hint
    declined = set(r.case.expect.declined_include)
    offered = {o.offer_id for o in hint.upsell}
    return declined <= set(hint.declined_offer_ids) and not declined & offered


# --- мягкие ------------------------------------------------------------------


def no_unverified_numbers(r: CaseResult) -> bool | None:
    if r.response is None:
        return None
    return "unverified_number" not in r.response.manager_hint.risk_flags


def language_matches(r: CaseResult) -> bool | None:
    """Язык ответа = язык клиента (ожидаемый в кейсе или определённый по сообщению)."""
    if r.response is None:
        return None
    expected = r.case.expect.language or detect_language(r.case.request.message)
    if expected is None:
        return None
    return r.response.client_reply.language == expected


# --- ожидания кейса ----------------------------------------------------------


def behavior_failures(r: CaseResult) -> list[str]:
    """Человекочитаемый список невыполненных ожиданий кейса (пусто — всё выполнено)."""
    if r.response is None:
        return [f"нет ответа: {r.error}"]
    e, reply, hint = r.case.expect, r.response.client_reply, r.response.manager_hint
    offered = [o.offer_id for o in hint.upsell]
    hint_text = " ".join(
        [hint.summary, hint.next_best_action, hint.upsell_suppressed_reason or ""]
    ).lower()
    checks: list[tuple[bool, str]] = [
        (
            e.needs_manager is None or reply.needs_manager == e.needs_manager,
            f"needs_manager={reply.needs_manager}, ожидалось {e.needs_manager}",
        ),
        *(
            (ref in reply.kb_refs, f"нет {ref} в kb_refs {reply.kb_refs}")
            for ref in e.kb_refs_include
        ),
        (
            not e.intent_in or hint.intent in e.intent_in,
            f"intent={hint.intent}, ожидалось одно из {[str(i) for i in e.intent_in]}",
        ),
        (
            e.language is None or reply.language == e.language,
            f"language={reply.language}, ожидалось {e.language}",
        ),
        *((s in reply.text, f"в ответе нет «{s}»") for s in e.reply_contains),
        *((s not in reply.text, f"в ответе есть «{s}»") for s in e.reply_not_contains),
        *((s.lower() in hint_text, f"в подсказке нет «{s}»") for s in e.hint_contains),
        (not e.upsell_empty or not offered, f"допродажа не пустая: {offered}"),
        (
            not e.upsell_include_any or bool(set(offered) & set(e.upsell_include_any)),
            f"нет ни одного из {e.upsell_include_any} в допродаже {offered}",
        ),
        *((oid not in offered, f"{oid} предложен, хотя не должен") for oid in e.upsell_exclude),
        *(
            (oid in hint.declined_offer_ids, f"{oid} не распознан как отклонённый")
            for oid in e.declined_include
        ),
        *(
            (f in hint.risk_flags, f"нет флага {f} в {hint.risk_flags}")
            for f in e.risk_flags_include
        ),
    ]
    return [message for ok, message in checks if not ok]


def behavior_ok(r: CaseResult) -> bool:
    return not behavior_failures(r)


# --- агрегирование -----------------------------------------------------------

MetricFn = Callable[[CaseResult], bool | None]

METRICS: tuple[tuple[str, MetricKind, float | None, MetricFn], ...] = (
    ("Валидность схемы ответа", HARD, 1.0, schema_valid),
    ("kb_refs валидны", HARD, 1.0, kb_refs_valid),
    ("offer_id ⊆ кандидатов", HARD, 1.0, offers_within_candidates),
    ("Подавление допродажи в S4", HARD, 1.0, upsell_suppressed),
    ("Отклонённое не предлагается (S7)", HARD, 1.0, declined_not_offered),
    ("Нет непроверенных чисел", SOFT, 0.95, no_unverified_numbers),
    ("Язык ответа = язык клиента", SOFT, 0.95, language_matches),
    ("Ожидания кейсов выполнены", INFO, None, behavior_ok),
)


def compute_metrics(results: list[CaseResult]) -> list[MetricResult]:
    metrics = []
    for name, kind, threshold, fn in METRICS:
        outcomes = [(r.case.id, fn(r)) for r in results]
        applicable = [(cid, ok) for cid, ok in outcomes if ok is not None]
        passed = sum(1 for _, ok in applicable if ok)
        metrics.append(
            MetricResult(
                name=name,
                kind=kind,
                value=passed / len(applicable) if applicable else None,
                threshold=threshold,
                applicable=len(applicable),
                failed_cases=[cid for cid, ok in applicable if not ok],
            )
        )
    return metrics

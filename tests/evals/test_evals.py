"""Критерий M4: evals покрывают S1–S10 и правила допродажи; жёсткие метрики = 100% на fake.

Метрики проверяются и «от противного»: на подделанных ответах они обязаны падать.
"""

import asyncio

import pytest

from app.core.models import AssistResponse
from app.kb.models import KnowledgeBase
from evals.cases import EvalCase, load_cases
from evals.metrics import (
    HARD,
    CaseResult,
    behavior_failures,
    compute_metrics,
    declined_not_offered,
    kb_refs_valid,
    language_matches,
    no_unverified_numbers,
    offers_within_candidates,
    schema_valid,
    upsell_suppressed,
)
from evals.run import EvalRun, render_report, run_evals


@pytest.fixture(scope="module")
def cases() -> list[EvalCase]:
    return load_cases()


@pytest.fixture(scope="module")
def fake_run() -> EvalRun:
    return asyncio.run(run_evals("fake"))


# --- набор кейсов ---


def test_cases_cover_every_spec_scenario(cases: list[EvalCase]) -> None:
    assert len(cases) >= 12
    assert {c.scenario for c in cases} >= {f"S{i}" for i in range(1, 11)}
    assert len({c.id for c in cases}) == len(cases), "id кейсов уникальны"


def test_every_upsell_rule_has_a_case(cases: list[EvalCase], demo_kb: KnowledgeBase) -> None:
    mentioned = {
        offer
        for c in cases
        for offer in (
            *c.expect.upsell_include_any,
            *c.expect.upsell_exclude,
            *c.expect.declined_include,
        )
    }
    missing = {r.id for r in demo_kb.upsell_rules if r.offer_id not in mentioned}

    assert not missing, f"нет eval-кейса на правила: {sorted(missing)}"


def test_case_references_exist_in_kb(cases: list[EvalCase], demo_kb: KnowledgeBase) -> None:
    for c in cases:
        e = c.expect
        for ref in (
            *e.kb_refs_include,
            *e.upsell_include_any,
            *e.upsell_exclude,
            *e.declined_include,
        ):
            assert demo_kb.get(ref) is not None, (c.id, ref)


# --- прогон на fake ---


def test_hard_metrics_are_100_percent_on_fake(fake_run: EvalRun) -> None:
    hard = [m for m in fake_run.metrics if m.kind == HARD]

    assert hard
    for metric in hard:
        assert metric.value == 1.0, (metric.name, metric.failed_cases)


def test_soft_metrics_meet_thresholds_on_fake(fake_run: EvalRun) -> None:
    for metric in fake_run.metrics:
        if metric.threshold is not None and metric.value is not None:
            assert metric.value >= metric.threshold, (metric.name, metric.failed_cases)


def test_report_header(fake_run: EvalRun) -> None:
    report = render_report(fake_run)

    for field in ("Дата", "Провайдер", "Модель", "PROMPT_VERSION", "Коммит", "Кейсов"):
        assert field in report
    assert "fake" in report
    assert "| Метрика |" in report


# --- метрики ловят нарушения ---


def result_for(case_id: str, run: EvalRun) -> CaseResult:
    return next(r for r in run.results if r.case.id == case_id)


def tamper(result: CaseResult, **changes: object) -> CaseResult:
    data = result.response.model_dump() if result.response else {}
    for path, value in changes.items():
        node = data
        *parents, leaf = path.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return CaseResult(
        case=result.case,
        response=AssistResponse.model_validate(data),
        candidates=result.candidates,
        kb=result.kb,
        error=None,
    )


def test_metrics_detect_violations(fake_run: EvalRun) -> None:
    s1 = result_for("s1_delivery_payment", fake_run)
    s4 = result_for("s4_broken_refund", fake_run)
    s7 = result_for("s7_bag_declined", fake_run)
    s9 = result_for("s9_english_delivery", fake_run)
    offer = {
        "offer_id": "product.unicorn",
        "title": "Единорог",
        "why": "—",
        "pitch": "—",
        "when_to_say": "—",
        "confidence": 0.9,
    }

    assert kb_refs_valid(s1) is True
    assert kb_refs_valid(tamper(s1, client_reply__kb_refs=["faq.teleport"])) is False
    assert offers_within_candidates(tamper(s1, manager_hint__upsell=[offer])) is False
    assert upsell_suppressed(s4) is True
    assert upsell_suppressed(tamper(s4, manager_hint__upsell=[offer])) is False
    assert declined_not_offered(s7) is True
    bag = dict(offer, offer_id="product.bag")
    assert declined_not_offered(tamper(s7, manager_hint__upsell=[bag])) is False
    assert (
        no_unverified_numbers(tamper(s1, manager_hint__risk_flags=["unverified_number"])) is False
    )
    assert language_matches(s9) is True
    assert language_matches(tamper(s9, client_reply__language="ru")) is False
    assert schema_valid(tamper(s1, meta__fallback_used=True)) is False


def test_not_applicable_metrics_return_none(fake_run: EvalRun) -> None:
    s1 = result_for("s1_delivery_payment", fake_run)

    assert upsell_suppressed(s1) is None  # не S4
    assert declined_not_offered(s1) is None  # не S7


def test_behavior_failures_are_explained(fake_run: EvalRun) -> None:
    s1 = result_for("s1_delivery_payment", fake_run)

    assert behavior_failures(s1) == []
    broken = tamper(s1, client_reply__needs_manager=True, client_reply__kb_refs=[])
    failures = behavior_failures(broken)
    assert any("needs_manager" in f for f in failures)
    assert any("faq.delivery_regions" in f for f in failures)


def test_compute_metrics_on_empty_input() -> None:
    metrics = compute_metrics([])

    assert all(m.value is None for m in metrics)

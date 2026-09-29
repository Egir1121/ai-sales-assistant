"""Прогон evals и отчёт (SPEC §9):

    uv run python -m evals.run --provider fake|real [--out evals/report.md]

fake — детерминированный офлайн-прогон (он же проверяется в `make check`);
real — реальная модель из настроек (LLM_PROVIDER=anthropic, нужен ANTHROPIC_API_KEY).
Код выхода 1, если какая-то жёсткая метрика ниже 100%; 2 — прогон невозможен (нет ключа).
"""

import argparse
import asyncio
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.config import Settings
from app.container import build_container
from app.core.pipeline import AssistService
from app.kb.models import KnowledgeBase
from app.llm.prompts import PROMPT_VERSION
from evals.cases import EvalCase, load_cases
from evals.metrics import (
    HARD,
    CaseResult,
    MetricResult,
    behavior_failures,
    compute_metrics,
)

Provider = Literal["fake", "real"]
DEFAULT_OUT = Path(__file__).parent / "report.md"
CONCURRENCY = 4


class ProviderUnavailableError(Exception):
    """Прогон на выбранном провайдере невозможен (например, нет API-ключа)."""


@dataclass(frozen=True)
class EvalRun:
    provider: Provider
    model: str
    started_at: datetime
    commit: str
    results: list[CaseResult]
    metrics: list[MetricResult]


def _settings(provider: Provider) -> Settings:
    try:
        return Settings(llm_provider="fake" if provider == "fake" else "anthropic")
    except ValidationError as exc:
        raise ProviderUnavailableError(
            "для --provider real нужен ANTHROPIC_API_KEY в окружении или .env"
        ) from exc


async def _run_case(
    service: AssistService, kb: KnowledgeBase, case: EvalCase, limit: asyncio.Semaphore
) -> CaseResult:
    candidates = tuple(c.offer_id for c in service.prepare(case.request).candidates)
    async with limit:
        try:
            response = await service.assist(case.request)
        except Exception as exc:  # отчёт должен собраться, даже если пайплайн упал на кейсе
            return CaseResult(case, None, candidates, kb, error=repr(exc))
    return CaseResult(case, response, candidates, kb)


async def run_evals(provider: Provider, cases: list[EvalCase] | None = None) -> EvalRun:
    container = build_container(_settings(provider))
    cases = cases if cases is not None else load_cases()
    started_at = datetime.now(UTC)
    limit = asyncio.Semaphore(CONCURRENCY)
    results = list(
        await asyncio.gather(*(_run_case(container.assist, container.kb, c, limit) for c in cases))
    )
    return EvalRun(
        provider=provider,
        model=container.llm.model,
        started_at=started_at,
        commit=_commit(),
        results=results,
        metrics=compute_metrics(results),
    )


def _commit() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", ":!evals/report.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "неизвестен"
    return f"{sha} (+ незакоммиченные изменения)" if dirty else sha


# --- отчёт -------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _status(m: MetricResult) -> str:
    if m.value is None:
        return "н/п"
    if m.threshold is None:
        return "ℹ️"
    return "✅" if m.value >= m.threshold else "❌"


def render_report(run: EvalRun) -> str:
    lines = [
        "# Отчёт evals",
        "",
        f"- **Дата:** {run.started_at:%Y-%m-%d %H:%M} UTC",
        f"- **Провайдер:** {run.provider}",
        f"- **Модель:** {run.model}",
        f"- **PROMPT_VERSION:** {PROMPT_VERSION}",
        f"- **Коммит:** {run.commit}",
        f"- **Кейсов:** {len(run.results)}",
    ]
    responses = [r.response for r in run.results if r.response is not None]
    if run.provider == "real" and responses:
        latencies = [r.meta.latency_ms for r in responses]
        costs = [r.meta.cost_usd for r in responses if r.meta.cost_usd is not None]
        p95 = statistics.quantiles(latencies, n=20)[-1] if len(latencies) > 1 else latencies[0]
        lines += [
            f"- **Токены:** вход {sum(r.meta.tokens_in for r in responses)}, "
            f"выход {sum(r.meta.tokens_out for r in responses)}",
            f"- **Задержка:** средняя {statistics.mean(latencies):.0f} мс, "
            f"p50 {statistics.median(latencies):.0f} мс, p95 {p95:.0f} мс",
            f"- **Стоимость прогона:** ${sum(costs):.4f}",
        ]

    lines += [
        "",
        "## Метрики (SPEC §9)",
        "",
        "| Метрика | Тип | Значение | Порог | Кейсов | Статус |",
        "|---|---|---|---|---|---|",
    ]
    for m in run.metrics:
        lines.append(
            f"| {m.name} | {m.kind} | {_pct(m.value)} | {_pct(m.threshold)} "
            f"| {m.applicable} | {_status(m)} |"
        )
    lines += [
        "",
        "Вежливость и ясность (LLM-судья, опционально) — не измерялась: нужна реальная модель.",
        "",
        "## Кейсы",
        "",
        "| id | Сценарий | Итог | Что не так |",
        "|---|---|---|---|",
    ]
    failing_metrics = {
        cid: [m.name for m in run.metrics if cid in m.failed_cases]
        for cid in (r.case.id for r in run.results)
    }
    for r in run.results:
        problems = failing_metrics[r.case.id] + behavior_failures(r)
        mark = "✅" if not problems else "❌"
        detail = "; ".join(dict.fromkeys(problems)).replace("|", "\\|") or ""
        lines.append(f"| `{r.case.id}` | {r.case.scenario} | {mark} | {detail} |")
    return "\n".join(lines) + "\n"


def _summary(run: EvalRun) -> str:
    rows = [f"{m.name}: {_pct(m.value)} {_status(m)}" for m in run.metrics]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    parser.add_argument("--provider", choices=["fake", "real"], default="fake")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    try:
        run = asyncio.run(run_evals(args.provider))
    except ProviderUnavailableError as exc:
        print(f"Прогон невозможен: {exc}", file=sys.stderr)
        return 2

    args.out.write_text(render_report(run), encoding="utf-8")
    print(_summary(run))
    print(f"\nОтчёт: {args.out}")
    hard_ok = all(m.value in (None, 1.0) for m in run.metrics if m.kind == HARD)
    return 0 if hard_ok else 1


if __name__ == "__main__":
    sys.exit(main())

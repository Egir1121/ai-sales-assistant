"""Схема eval-кейсов (`evals/cases.yaml`).

Ожидания описывают поведение по SPEC, а не «как сейчас отвечает».
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.models import AssistRequest
from app.kb.models import Intent

CASES_PATH = Path(__file__).parent / "cases.yaml"

Scenario = Literal["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "rule"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expect(_Strict):
    needs_manager: bool | None = None
    kb_refs_include: list[str] = Field(default_factory=list)
    intent_in: list[Intent] = Field(default_factory=list)
    language: str | None = None
    reply_contains: list[str] = Field(default_factory=list)
    reply_not_contains: list[str] = Field(default_factory=list)
    hint_contains: list[str] = Field(default_factory=list)
    """Подстроки в summary / next_best_action / upsell_suppressed_reason (подсказка менеджеру)."""
    upsell_empty: bool = False
    upsell_include_any: list[str] = Field(default_factory=list)
    upsell_exclude: list[str] = Field(default_factory=list)
    declined_include: list[str] = Field(default_factory=list)
    risk_flags_include: list[str] = Field(default_factory=list)


class EvalCase(_Strict):
    id: str
    scenario: Scenario
    title: str
    request: AssistRequest
    expect: Expect


def load_cases(path: Path = CASES_PATH) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw]

"""CLI для быстрой проверки (SPEC §4):

    uv run python -m app.cli "Сколько стоит доставка?" [--dialog d.json] [--lead lead.json] [--json]

dialog — список {"role": "client"|"manager", "text": "..."}; lead — объект lead из SPEC §4.
"""

import argparse
import asyncio
import sys
import textwrap
from pathlib import Path

from pydantic import TypeAdapter

from app.config import Settings
from app.container import build_container
from app.core.models import AssistRequest, AssistResponse, DialogTurn, Lead


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="AI Sales Assistant")
    parser.add_argument("message", help="сообщение клиента")
    parser.add_argument("--dialog", type=Path, help="JSON с историей диалога")
    parser.add_argument("--lead", type=Path, help="JSON с данными сделки")
    parser.add_argument("--json", action="store_true", help="вывести ответ API как JSON")
    args = parser.parse_args(argv)

    request = AssistRequest(
        message=args.message,
        dialog=_read(args.dialog, list[DialogTurn]) if args.dialog else [],
        lead=_read(args.lead, Lead) if args.lead else Lead(),
    )
    service = build_container(settings or Settings()).assist
    response = asyncio.run(service.assist(request))

    print(response.model_dump_json(indent=2) if args.json else render(response))
    return 0


def _read[T](path: Path, model: type[T]) -> T:
    return TypeAdapter(model).validate_json(path.read_text(encoding="utf-8"))


def render(response: AssistResponse) -> str:
    reply, hint, meta = response.client_reply, response.manager_hint, response.meta
    lines = [
        "═══ ОТВЕТ КЛИЕНТУ (черновик) ═══",
        textwrap.fill(reply.text, width=100),
        "",
        f"Язык: {reply.language} · Источники: {', '.join(reply.kb_refs) or '—'}"
        + (" · ⚠ нужен менеджер" if reply.needs_manager else ""),
        "",
        "═══ ПОДСКАЗКА МЕНЕДЖЕРУ ═══",
        f"Сводка: {hint.summary}",
        f"Интент: {hint.intent} · Тон: {hint.sentiment}",
    ]
    if hint.upsell:
        lines.append("Допродажа:")
        for o in hint.upsell:
            lines += [
                f"  • {o.title} [{o.offer_id}], уверенность {o.confidence:.1f}",
                f"    Почему: {o.why}",
                f"    Фраза: «{o.pitch}»",
                f"    Когда: {o.when_to_say}",
            ]
    else:
        lines.append(
            f"Допродажа: нет — {hint.upsell_suppressed_reason or 'нет подходящих кандидатов'}"
        )
    lines += [
        f"Отклонено клиентом: {', '.join(hint.declined_offer_ids) or '—'}",
        f"Следующий шаг: {hint.next_best_action}",
        f"Риски: {', '.join(hint.risk_flags) or '—'}",
        "",
        f"[{meta.provider}/{meta.model} · prompt {meta.prompt_version} · {meta.latency_ms} мс"
        f" · токены {meta.tokens_in}/{meta.tokens_out}"
        + (" · FALLBACK" if meta.fallback_used else "")
        + (
            f" · guardrails: {', '.join(meta.guardrails_applied)}"
            if meta.guardrails_applied
            else ""
        )
        + "]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())

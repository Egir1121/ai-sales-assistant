"""Текст примечания: «💡 Подсказка», затем «✉️ Черновик ответа», в конце — prompt и request_id."""

from app.core.models import AssistResponse

_SENTIMENT = {"positive": "позитивный", "neutral": "нейтральный", "negative": "негативный"}


def format_note(response: AssistResponse) -> str:
    hint, reply, meta = response.manager_hint, response.client_reply, response.meta
    lines = [
        "💡 Подсказка",
        hint.summary,
        f"Интент: {hint.intent} · тон: {_SENTIMENT[hint.sentiment]}",
    ]
    if meta.fallback_used:
        lines.append("⚠ LLM недоступен — ответьте клиенту вручную.")
    if hint.upsell:
        lines.append("Предложить:")
        for offer in hint.upsell:
            lines += [
                f"• {offer.title} — {offer.why}",
                f"  Фраза: «{offer.pitch}»",
                f"  Когда: {offer.when_to_say}",
            ]
    elif hint.upsell_suppressed_reason:
        lines.append(f"Допродажа: нет — {hint.upsell_suppressed_reason}")
    if hint.declined_offer_ids:
        lines.append(f"Клиент уже отказался: {', '.join(hint.declined_offer_ids)}")
    lines.append(f"Следующий шаг: {hint.next_best_action}")
    if hint.risk_flags:
        lines.append(f"Риски: {', '.join(hint.risk_flags)}")

    lines += ["", "✉️ Черновик ответа", reply.text]
    if reply.needs_manager:
        lines.append("(нужна проверка менеджера: данных в базе знаний не хватило)")
    lines += [
        "",
        f"— prompt {meta.prompt_version} · {meta.provider} · request_id {response.request_id}",
    ]
    return "\n".join(lines)

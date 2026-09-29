"""Промпты и их рендер. Любая правка → навык /prompt-change и новая PROMPT_VERSION.

Порядок в user-сообщении: <knowledge_base> (стабильный, кэшируемый префикс), затем
<upsell_candidates>, <declined>, <lead>, <dialog>, <client_message>. Текст клиента и менеджера
экранируется: закрыть наши теги из сообщения нельзя (инвариант 5).
"""

from functools import cache, lru_cache
from pathlib import Path

from app.kb.models import Company, FaqEntry, KBEntry, Policy, Product
from app.llm.base import LLMRequest, PromptContext
from app.upsell.models import UpsellCandidate

PROMPT_VERSION = "v1"

_DIR = Path(__file__).parent


@cache
def _template(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


def format_price(price: int, currency: str = "RUB") -> str:
    amount = f"{price:,}".replace(",", " ")
    return f"{amount} ₽" if currency == "RUB" else f"{amount} {currency}"


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_system(company: Company) -> str:
    return (
        _template(f"system_{PROMPT_VERSION}.md")
        .replace("{company_name}", company.name)
        .replace("{company_tone}", company.tone)
    )


def _render_entry(entry: KBEntry) -> str:
    match entry:
        case FaqEntry():
            return f"[{entry.id}] Вопросы: {'; '.join(entry.questions)}\nОтвет: {entry.answer}"
        case Product():
            lines = [f"[{entry.id}] {entry.title} — {format_price(entry.price, entry.currency)}"]
            if entry.description:
                lines.append(f"Описание: {entry.description}")
            lines.append(f"В наличии: {'да' if entry.in_stock else 'нет'}")
            return "\n".join(lines)
        case Policy():
            return f"[{entry.id}] Политика: {entry.text}"


@lru_cache(maxsize=64)
def render_kb(entries: tuple[KBEntry, ...]) -> str:
    body = "\n\n".join(_render_entry(e) for e in entries)
    return f"<knowledge_base>\n{body}\n</knowledge_base>"


def _render_candidate(c: UpsellCandidate) -> str:
    parts = [
        c.offer_id,
        c.title,
        format_price(c.price, c.currency),
        f"правило {c.rule_id}: {c.why}",
    ]
    if c.if_intents_any:
        parts.append(f"только при интенте: {', '.join(c.if_intents_any)}")
    if c.already_offered:
        parts.append("уже предлагали")
    return "- " + " | ".join(parts)


def render_dynamic(ctx: PromptContext) -> str:
    candidates = "\n".join(_render_candidate(c) for c in ctx.candidates) or "(нет)"
    declined = "\n".join(f"- {pid}" for pid in sorted(ctx.facts.declined_product_ids)) or "(нет)"
    lead = "\n".join(
        [
            f"Имя клиента: {escape(ctx.client_name) if ctx.client_name else 'неизвестно'}",
            f"Этап сделки: {escape(ctx.stage) if ctx.stage else 'неизвестно'}",
            "Товары сделки: " + (", ".join(sorted(ctx.facts.deal_product_ids)) or "нет"),
        ]
    )
    dialog = "\n".join(f"[{t.role}]: {escape(t.text)}" for t in ctx.dialog) or "(пусто)"
    return (
        f"<upsell_candidates>\n{candidates}\n</upsell_candidates>\n\n"
        f"<declined>\n{declined}\n</declined>\n\n"
        f"<lead>\n{lead}\n</lead>\n\n"
        f"<dialog>\n{dialog}\n</dialog>\n\n"
        f"<client_message>\n{escape(ctx.message)}\n</client_message>"
    )


def build_request(ctx: PromptContext) -> LLMRequest:
    return LLMRequest(
        system=render_system(ctx.kb.company),
        kb_block=render_kb(ctx.retrieval.context),
        dynamic_block=render_dynamic(ctx),
        context=ctx,
    )

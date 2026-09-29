from typing import Any

from app.kb.models import KnowledgeBase
from app.kb.retriever import (
    FullContextRetriever,
    KeywordRetriever,
    make_retriever,
)


def _kb(data: dict[str, Any]) -> KnowledgeBase:
    return KnowledgeBase.model_validate(data)


def test_keyword_ranks_matching_faq_first(kb_data: dict[str, Any]) -> None:
    hits = KeywordRetriever(_kb(kb_data)).retrieve("Сколько везти доставку?").hits

    assert hits[0].entry.id == "faq.delivery"
    assert all(h.score > 0 for h in hits)


def test_keyword_finds_product_by_alias(kb_data: dict[str, Any]) -> None:
    hits = KeywordRetriever(_kb(kb_data)).retrieve("а икс 15 ещё есть?").hits

    assert hits[0].entry.id == "product.x15"


def test_other_word_forms_of_the_same_root_match(kb_data: dict[str, Any]) -> None:
    # Snowball: «доставите» → «достав», «доставка» → «доставк»; совпадают по префиксу основы
    hits = KeywordRetriever(_kb(kb_data)).retrieve("Когда доставите?").hits

    assert hits[0].entry.id == "faq.delivery"


def test_exact_stem_outranks_prefix_match(kb_data: dict[str, Any]) -> None:
    kb_data["faq"].append(
        {"id": "faq.delivery_time", "questions": ["когда доставите"], "answer": "Завтра."}
    )
    hits = KeywordRetriever(_kb(kb_data)).retrieve("Когда доставите?").hits

    assert hits[0].entry.id == "faq.delivery_time"


def test_irrelevant_or_empty_query_returns_no_hits(kb_data: dict[str, Any]) -> None:
    retriever = KeywordRetriever(_kb(kb_data))

    assert retriever.retrieve("").hits == ()
    assert retriever.retrieve("   ").hits == ()
    assert retriever.retrieve("квантовый телепорт").hits == ()


def test_keyword_context_is_top_k_plus_all_policies(kb_data: dict[str, Any]) -> None:
    result = KeywordRetriever(_kb(kb_data), k=1).retrieve("доставка")

    assert [e.id for e in result.context] == ["faq.delivery", "policy.discount"]


def test_full_context_includes_whole_kb_in_stable_order(kb_data: dict[str, Any]) -> None:
    kb = _kb(kb_data)
    retriever = FullContextRetriever(kb)

    first = retriever.retrieve("доставка")
    second = retriever.retrieve("совсем другой вопрос")

    assert [e.id for e in first.context] == [e.id for e in kb.entries]
    assert first.context is second.context  # один и тот же объект → стабильный кэшируемый префикс
    assert first.hits[0].entry.id == "faq.delivery"


def test_auto_mode_switches_to_keyword_for_large_kb(kb_data: dict[str, Any]) -> None:
    assert isinstance(make_retriever(_kb(kb_data), "auto"), FullContextRetriever)

    kb_data["faq"] += [
        {"id": f"faq.filler_{i}", "questions": [f"вопрос {i}"], "answer": "Ответ. " * 30}
        for i in range(250)
    ]
    assert isinstance(make_retriever(_kb(kb_data), "auto"), KeywordRetriever)


def test_explicit_mode_is_respected(kb_data: dict[str, Any]) -> None:
    kb = _kb(kb_data)

    assert isinstance(make_retriever(kb, "keyword"), KeywordRetriever)
    assert isinstance(make_retriever(kb, "full"), FullContextRetriever)

from app.kb.text import contains_phrase, tokenize


def test_tokenize_normalizes_case_yo_and_word_forms() -> None:
    assert tokenize("Доставку в КАЗАНЬ") == tokenize("доставка казани")


def test_tokenize_drops_stopwords_and_punctuation() -> None:
    assert tokenize("а и, в — на?!") == []


def test_tokenize_keeps_latin_and_digits() -> None:
    assert tokenize("Ноутбук X15, 16 ГБ") == ["ноутбук", "x15", "16", "гб"]


def test_yo_is_treated_as_e() -> None:
    assert tokenize("учёба") == tokenize("учеба")


def test_contains_phrase_respects_word_boundaries() -> None:
    text = tokenize("хочу сумку к икс 15")

    assert contains_phrase(text, tokenize("сумка"))
    assert contains_phrase(text, tokenize("икс 15"))
    assert not contains_phrase(text, tokenize("икс 1"))
    assert not contains_phrase(text, [])

import copy
from typing import Any

import pytest

from app.config import Settings
from app.kb.loader import load_kb
from app.kb.models import KnowledgeBase
from tests.helpers import DEMO_KB_PATH, MINIMAL_KB


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Настройки по умолчанию, изолированные от .env и переменных окружения разработчика."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return Settings(_env_file=None)


@pytest.fixture
def kb_data() -> dict[str, Any]:
    """Минимальная валидная БЗ в виде dict — тесты портят её точечно."""
    return copy.deepcopy(MINIMAL_KB)


@pytest.fixture(scope="session")
def demo_kb() -> KnowledgeBase:
    return load_kb(DEMO_KB_PATH)

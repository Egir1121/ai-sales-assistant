import copy
from typing import Any

import pytest

from app.config import Settings
from tests.helpers import MINIMAL_KB


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

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.kb.loader import KBError
from app.main import create_app
from tests.helpers import write_kb


def test_app_loads_demo_kb_on_startup(settings: Settings) -> None:
    app = create_app(settings)

    assert app.state.kb.company.name
    assert app.state.retriever is not None


def test_app_refuses_to_start_with_broken_kb(
    settings: Settings, tmp_path: Path, kb_data: dict[str, Any]
) -> None:
    kb_data["upsell_rules"][0]["offer_id"] = "product.nope"
    broken = settings.model_copy(update={"kb_path": write_kb(tmp_path, kb_data)})

    with pytest.raises(KBError, match=r"product\.nope"):
        create_app(broken)

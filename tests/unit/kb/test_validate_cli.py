from pathlib import Path
from typing import Any

import pytest

from app.kb.validate import main
from tests.helpers import write_kb


def test_valid_kb_prints_summary(
    tmp_path: Path, kb_data: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(write_kb(tmp_path, kb_data))])

    assert code == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "2 faq" in out
    assert "1 правил" in out


def test_broken_kb_exits_with_error(
    tmp_path: Path, kb_data: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    kb_data["upsell_rules"][0]["offer_id"] = "product.nope"

    code = main([str(write_kb(tmp_path, kb_data))])

    assert code == 1
    assert "product.nope" in capsys.readouterr().err

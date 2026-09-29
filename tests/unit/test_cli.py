"""Критерий M2: CLI выдаёт два блока."""

import json
from pathlib import Path

import pytest

from app.cli import main
from app.config import Settings


def test_cli_prints_two_blocks(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["Сколько стоит X15?"], settings=settings)

    out = capsys.readouterr().out
    assert code == 0
    assert "ОТВЕТ КЛИЕНТУ" in out
    assert "ПОДСКАЗКА МЕНЕДЖЕРУ" in out
    assert "89 990 ₽" in out


def test_cli_reads_dialog_file(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dialog = tmp_path / "dialog.json"
    dialog.write_text(
        json.dumps(
            [
                {"role": "client", "text": "Беру X15"},
                {"role": "manager", "text": "Сумку добавить?"},
                {"role": "client", "text": "Сумка не нужна"},
            ],
            ensure_ascii=False,
        )
    )

    main(["Когда доставка?", "--dialog", str(dialog)], settings=settings)

    assert "product.bag" in capsys.readouterr().out.split("Отклонено")[1]


def test_cli_json_output(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    main(["Доставка?", "--json"], settings=settings)

    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"request_id", "client_reply", "manager_hint", "meta"}

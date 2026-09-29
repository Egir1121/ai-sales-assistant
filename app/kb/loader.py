"""Загрузка БЗ из YAML с понятными ошибками: файл, строка, id записи, поле."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.kb.models import KnowledgeBase

_YAML_SUFFIXES = {".yaml", ".yml"}

_RU_MESSAGES = {
    "missing": "обязательное поле отсутствует",
    "extra_forbidden": "неизвестное поле",
}


class KBError(Exception):
    """БЗ не прошла загрузку или валидацию. Сервис с такой БЗ не стартует."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        super().__init__(
            f"Невалидная база знаний: {path}\n" + "\n".join(f"  - {p}" for p in problems)
        )


def load_kb(path: Path | str) -> KnowledgeBase:
    """Загружает БЗ из YAML-файла или из каталога ровно с одним YAML (подкаталоги не читаются)."""
    file = _resolve(Path(path))
    raw = _read_yaml(file)
    try:
        return KnowledgeBase.model_validate(raw)
    except ValidationError as exc:
        raise KBError(file, _format_errors(exc, raw)) from None


def _resolve(path: Path) -> Path:
    if not path.exists():
        raise KBError(path, ["путь не найден"])
    if path.is_file():
        return path
    files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix in _YAML_SUFFIXES)
    if len(files) != 1:
        names = ", ".join(p.name for p in files) or "—"
        raise KBError(path, [f"ожидается ровно один YAML-файл БЗ, найдено {len(files)}: {names}"])
    return files[0]


def _read_yaml(file: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f"{file}:{mark.line + 1}:{mark.column + 1}" if mark else str(file)
        raise KBError(file, [f"{where}: синтаксическая ошибка YAML: {exc.problem}"]) from None
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise KBError(file, [f"не удалось прочитать файл: {exc}"]) from None

    if raw is None:
        raise KBError(file, ["файл пуст"])
    if not isinstance(raw, dict):
        raise KBError(
            file, ["на верхнем уровне ожидается словарь (version, company, faq, products, …)"]
        )
    return raw


def _format_errors(exc: ValidationError, raw: dict[str, Any]) -> list[str]:
    problems = []
    for error in exc.errors():
        message = _RU_MESSAGES.get(error["type"], error["msg"].removeprefix("Value error, "))
        if error["type"] == "enum":
            message = f"допустимые значения: {error.get('ctx', {}).get('expected', '')}"
        if error["type"] not in ("missing", "value_error", "assertion_error", "model_type"):
            message += f" (получено: {error['input']!r})"
        location = _format_location(error["loc"], raw)
        for line in message.splitlines():
            problems.append(f"{location}: {line}" if location else line)
    return problems


def _format_location(loc: tuple[int | str, ...], raw: dict[str, Any]) -> str:
    """('products', 0, 'price') → 'products[0] (product.x15).price'."""
    parts: list[str] = []
    node: Any = raw
    for item in loc:
        if isinstance(item, int) and parts:
            node = node[item] if isinstance(node, list) and item < len(node) else None
            parts[-1] += f"[{item}]"
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                parts[-1] += f" ({node['id']})"
        else:
            parts.append(str(item))
            node = node.get(item) if isinstance(node, dict) else None
    return ".".join(parts)

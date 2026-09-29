"""Проверка направления зависимостей между слоями (см. CLAUDE.md, «Архитектура»).

core/kb/upsell — чистый Python + Pydantic: без веб-фреймворка, HTTP-клиентов и SDK провайдеров,
и без обратных импортов из api/ и integrations/.
"""

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parents[2] / "app"

FORBIDDEN_EXTERNAL = {"fastapi", "starlette", "uvicorn", "httpx", "httpx2", "anthropic", "requests"}
FORBIDDEN_INTERNAL = {"app.api", "app.integrations", "app.main", "app.llm.anthropic_client"}
PURE_LAYERS = ["core", "kb", "upsell"]


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def violations(source: str) -> set[str]:
    found = set()
    for module in imported_modules(source):
        if module.split(".")[0] in FORBIDDEN_EXTERNAL:
            found.add(module)
        if any(module == bad or module.startswith(bad + ".") for bad in FORBIDDEN_INTERNAL):
            found.add(module)
    return found


def test_checker_detects_violations() -> None:
    source = (
        "import httpx\nfrom fastapi import Depends\nfrom app.api.deps import x\nimport pydantic\n"
    )

    assert violations(source) == {"httpx", "fastapi", "app.api.deps"}


@pytest.mark.parametrize("layer", PURE_LAYERS)
def test_pure_layers_do_not_import_infrastructure(layer: str) -> None:
    layer_dir = APP_DIR / layer
    assert layer_dir.is_dir(), f"нет пакета app/{layer}"

    bad = {
        f"{path.relative_to(APP_DIR.parent)}: {module}"
        for path in layer_dir.rglob("*.py")
        for module in violations(path.read_text())
    }

    assert not bad, "запрещённые импорты:\n" + "\n".join(sorted(bad))

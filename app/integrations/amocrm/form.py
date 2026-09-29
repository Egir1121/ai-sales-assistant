"""Разбор тела вебхука amoCRM: `x-www-form-urlencoded` с вложенными ключами
`message[add][0][author][name]=...` → вложенные dict/list."""

import re
import urllib.parse
from typing import Any

_KEY = re.compile(r"^([^\[\]]+)((?:\[[^\[\]]*\])*)$")
_PART = re.compile(r"\[([^\[\]]*)\]")


def parse_form(body: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for key, value in urllib.parse.parse_qsl(body, keep_blank_values=True):
        match = _KEY.match(key)
        if not match:
            continue
        path = [match.group(1), *_PART.findall(match.group(2))]
        node = root
        for part in path[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[path[-1]] = value
    result: dict[str, Any] = _listify(root)
    return result


def _listify(node: Any) -> Any:
    """{"0": ..., "1": ...} → [..., ...] — так amoCRM кодирует массивы."""
    if not isinstance(node, dict):
        return node
    converted = {k: _listify(v) for k, v in node.items()}
    if converted and all(k.isdigit() for k in converted):
        return [converted[k] for k in sorted(converted, key=int)]
    return converted

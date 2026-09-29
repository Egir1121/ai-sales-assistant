import urllib.parse
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parents[2] / "fixtures" / "amocrm"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _flatten(v, f"{prefix}[{k}]" if prefix else k)]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in _flatten(v, f"{prefix}[{i}]")]
    return [(prefix, str(obj))]


def form(
    kind: str,
    msg_id: str,
    text: str,
    *,
    talk_id: str = "500",
    element_id: str = "4242",
    element_type: str = "2",
    attachment: str | None = None,
) -> str:
    """Payload в формате amoCRM (как в документации) для входящего (`message`) или
    исходящего (`outgoing_message`) сообщения."""
    message: dict[str, Any] = {
        "id": msg_id,
        "chat_id": "chat-1",
        "talk_id": talk_id,
        "contact_id": "777",
        "text": text,
        "created_at": "1727600000",
        "message_type": "picture" if attachment else "text",
        "origin": "telegram",
        "author": {
            "id": "a-1",
            "type": "external" if kind == "message" else "internal",
            "name": "X",
        },
        "element_id": element_id,
        "element_type": element_type,
    }
    if attachment:
        message["attachment"] = {
            "type": attachment,
            "link": "https://x/y.gif",
            "file_name": "y.gif",
        }
    if kind == "outgoing_message":
        message["type"] = "outgoing"
    return urllib.parse.urlencode(_flatten({kind: {"add": [message]}}))

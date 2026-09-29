"""Демо-UI: страница, статика и пресеты сценариев S1–S10 (каждый должен проходить через API)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.models import AssistRequest
from app.main import create_app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def test_index_page(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Подсказка менеджеру" in html
    assert 'src="/static/app.js"' in html
    assert 'href="/static/styles.css"' in html


@pytest.mark.parametrize("asset", ["app.js", "styles.css", "scenarios.json"])
def test_static_assets(client: TestClient, asset: str) -> None:
    assert client.get(f"/static/{asset}").status_code == 200


def scenarios(client: TestClient) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = client.get("/static/scenarios.json").json()
    return data


def test_presets_cover_all_spec_scenarios(client: TestClient) -> None:
    assert [s["id"] for s in scenarios(client)] == [f"S{i}" for i in range(1, 11)]


def test_every_preset_is_a_valid_request_and_runs(client: TestClient) -> None:
    for scenario in scenarios(client):
        request = AssistRequest.model_validate(scenario["request"])
        assert scenario["title"], scenario["id"]
        assert scenario["expect"], scenario["id"]

        response = client.post("/v1/assist", json=request.model_dump())

        assert response.status_code == 200, (scenario["id"], response.text)
        assert response.json()["meta"]["fallback_used"] is False, scenario["id"]


def test_preset_products_exist_in_kb(client: TestClient) -> None:
    known = {p["id"] for p in client.get("/v1/kb/products").json()}

    for scenario in scenarios(client):
        assert set(scenario["request"].get("lead", {}).get("product_ids", [])) <= known

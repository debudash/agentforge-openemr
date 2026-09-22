"""/ready reports every dependency, including the Week 2 vision model, and never crashes."""

import pytest
from fastapi.testclient import TestClient

import copilot.service.app as service


@pytest.fixture
def client(monkeypatch):
    async def reachable(url, **_):
        return {"ok": True, "detail": "HTTP 200"}

    monkeypatch.setattr(service, "_reach", reachable)     # no network in unit tests
    return TestClient(service.app)


def test_ready_names_every_dependency(client):
    body = client.get("/ready").json()
    assert set(body["checks"]) == {"model_provider", "vision_model", "shared_secret", "observability", "openemr"}
    assert body["checks"]["vision_model"]["model"] == service.settings.vision_model


def test_ready_is_503_when_the_vision_model_is_not_allowlisted(client, monkeypatch):
    import dataclasses

    monkeypatch.setattr(service, "settings", dataclasses.replace(service.settings, vision_model="not/allowed", openemr_url="https://openemr.example"))
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["vision_model"]["ok"] is False
    assert resp.json()["checks"]["model_provider"]["ok"] is True, "the agent model is unaffected"


def test_health_stays_200_whatever_ready_says(client):
    assert client.get("/health").status_code == 200

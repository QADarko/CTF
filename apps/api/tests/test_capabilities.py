from __future__ import annotations

import json
from pathlib import Path

from apps.api.app.capabilities import CapabilityStatus, ManifestState, load_manifest
from apps.api.app.main import app


def test_checked_in_manifest_is_valid_and_inventory_is_complete():
    state = load_manifest()
    assert state.error is None
    assert state.manifest is not None
    assert len(state.manifest.capabilities) == 80
    assert {item.status for item in state.manifest.capabilities} == set(CapabilityStatus)
    assert all(item.evidence.code or item.evidence.tests or item.evidence.docs for item in state.manifest.capabilities)
    assert all(not item.gaps for item in state.manifest.capabilities if item.status == "IMPLEMENTED")


def test_capability_filters_and_summary_counts(client):
    response = client.get(
        "/api/v1/system/capabilities",
        params=[("status", "NOT_IMPLEMENTED"), ("priority", "P0")],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] == 80
    assert body["summary"]["matching"] == len(body["capabilities"])
    assert sum(body["summary"]["by_status"].values()) == 80
    assert sum(body["summary"]["by_priority"].values()) == 80
    assert body["capabilities"]
    assert all(item["status"] == "NOT_IMPLEMENTED" for item in body["capabilities"])
    assert all(item["priority"] == "P0" for item in body["capabilities"])


def test_system_status_is_public_and_does_not_expose_secrets(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "super-secret-ai-key")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "super-secret-minio-password")
    capabilities = client.get("/api/v1/system/capabilities")
    readiness = client.get("/api/v1/system/readiness")
    assert capabilities.status_code == 200
    assert readiness.status_code == 200
    serialized = json.dumps([capabilities.json(), readiness.json()])
    assert "super-secret-ai-key" not in serialized
    assert "super-secret-minio-password" not in serialized
    assert "AI_API_KEY" not in serialized
    assert "MINIO_ROOT_PASSWORD" not in serialized
    assert readiness.json()["pilot"]["completed"] is False


def test_invalid_manifest_degrades_safely(client, tmp_path: Path):
    invalid = tmp_path / "capabilities.yaml"
    invalid.write_text("capabilities: [not-valid", encoding="utf-8")
    state = load_manifest(invalid)
    assert state.manifest is None
    assert state.error == "Capability manifest is unavailable or invalid."

    previous = getattr(app.state, "capability_manifest", None)
    app.state.capability_manifest = ManifestState(error=state.error)
    try:
        response = client.get("/api/v1/system/capabilities")
        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "CAPABILITY_MANIFEST_UNAVAILABLE",
                "message": "Capability manifest is unavailable or invalid.",
            }
        }
        assert str(invalid) not in response.text
    finally:
        if previous is None:
            del app.state.capability_manifest
        else:
            app.state.capability_manifest = previous

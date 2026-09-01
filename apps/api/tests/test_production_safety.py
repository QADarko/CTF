from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.job_queue import create_document_job_queue
from packages.ctf_domain.malware import create_malware_scanner
from packages.ctf_domain.model_registry import ModelRegistry
from packages.ctf_domain.repository import InMemoryRepository
from packages.ctf_domain.runtime_safety import production_runtime_flags

ROOT = Path(__file__).resolve().parents[3]


def test_production_api_detects_production_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    flags = production_runtime_flags()
    assert flags["is_production"] is True
    assert flags["app_env"] == "production"


def test_production_api_rejects_noop_malware_scanner(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CTF_MALWARE_SCANNER", "noop")
    with pytest.raises(DomainError) as caught:
        create_malware_scanner("noop")
    assert caught.value.code == "MALWARE_SCANNER_REQUIRED"


def test_noop_scanner_rejected_in_production(monkeypatch):
    test_production_api_rejects_noop_malware_scanner(monkeypatch)


def test_production_requires_clamav():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert "clamav" in compose["services"]
    assert compose["services"]["clamav"].get("profiles") in (None, [], {})
    api = compose["services"]["api"]
    assert api["environment"]["CTF_MALWARE_SCANNER"] == "${CTF_MALWARE_SCANNER:-clamav}"
    assert "clamav" in api["depends_on"]


def test_production_api_enforces_model_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CTF_MODEL_REGISTRY", str(tmp_path / "missing.json"))
    registry = ModelRegistry()
    assert registry.enforced is True
    assert registry.is_available() is False


def test_production_model_registry_required(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CTF_ENFORCE_MODEL_REGISTRY", raising=False)
    assert ModelRegistry(enforced=None).enforced is True


def test_missing_registry_causes_readiness_failure(monkeypatch, tmp_path):
    from packages.ctf_domain.ai_runtime import AIExecutionService, FakeProvider

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CTF_MODEL_REGISTRY", str(tmp_path / "absent.json"))
    registry = ModelRegistry()
    service = AIExecutionService(InMemoryRepository(), FakeProvider(fixture_mode=True), model_registry=registry)
    status = service.readiness()
    assert status["ready"] is False
    assert any("registry" in item.lower() for item in status.get("limitations") or [])


def test_unapproved_model_route_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    registry.upsert({"provider": "OLLAMA", "model": "qwen2.5:3b", "approved_routes": [], "status": "CANDIDATE"})
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_production_api_uses_postgres_document_queue(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CTF_DOCUMENT_QUEUE", "in-process")
    with pytest.raises(DomainError) as caught:
        create_document_job_queue(InMemoryRepository())
    assert caught.value.code == "DOCUMENT_QUEUE_NOT_DURABLE"
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["services"]["api"]["environment"]["CTF_DOCUMENT_QUEUE"] == "postgres"


def test_upload_fails_when_clamav_unavailable(monkeypatch):
    monkeypatch.setenv("CTF_MALWARE_SCANNER", "clamav")
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PORT", "1")
    scanner = create_malware_scanner("clamav")
    with pytest.raises(DomainError) as caught:
        scanner.scan(b"hello")
    assert caught.value.code == "MALWARE_SCANNER_UNAVAILABLE"


def test_eicar_upload_quarantined(client, project, monkeypatch):
    monkeypatch.setenv("CTF_MALWARE_SCANNER", "eicar-test")
    infected = client.post(
        f"/api/v1/projects/{project['project']['id']}/attachments",
        headers=project["headers"],
        files={
            "file": (
                "eicar.txt",
                b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
                "text/plain",
            )
        },
    )
    assert infected.status_code == 422
    assert infected.json()["error"]["code"] in {"MALWARE_DETECTED", "UNSAFE_DOCUMENT"}


def test_compose_propagates_production_api_env():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]["environment"]
    for key in ("APP_ENV", "CTF_MALWARE_SCANNER", "CTF_ENFORCE_MODEL_REGISTRY", "CTF_DOCUMENT_QUEUE"):
        assert key in api

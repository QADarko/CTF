from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from apps.api.tests.test_ai_runtime import project_in, runtime, valid_output
from packages.ctf_domain.context_policy import ContextCompiler
from packages.ctf_domain.context_safety import AIRequestContext
from packages.ctf_domain.repository import InMemoryRepository


def test_ai_request_context_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AIRequestContext.model_validate({"focus": "ok", "raw_khal_dump": {"x": 1}})


def test_reality_event_never_in_ai_context():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    repo.create_resource(
        project,
        "REALITY_EVENT",
        {"raw_payload": {"device": "PUMP-17", "sample": [1, 2, 3]}},
        status="RECEIVED",
    )
    provider_service = runtime(repo, [valid_output(text="safe")])
    provider_service.execute(project, operation="REALITY_UPDATE", user_input="update reality")
    captured = json.dumps(provider_service.provider.calls)
    assert "REALITY_EVENT" not in captured
    assert "PUMP-17" not in captured
    assert "raw_payload" not in captured


def test_khal_raw_measurement_never_in_ai_context():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    repo.create_resource(
        project,
        "REALITY_EVENT",
        {
            "provider": "KHAL",
            "raw_measurement": {"voltage": 412, "raw": True},
            "khal_raw": {"frame": "AABBCC"},
        },
        status="RECEIVED",
    )
    evidence = repo.create_resource(
        project,
        "EVIDENCE",
        {
            "statement": "Normalized efficiency declined.",
            "source_provenance": "KHAL",
            "attribution": "NOT_ASSESSED",
        },
        status="CANDIDATE",
    )
    service = runtime(repo, [valid_output(text="interpret")])
    service.execute(project, operation="CLAIM_EVIDENCE_ASSESSMENT", user_input="assess evidence")
    captured = json.dumps(service.provider.calls)
    assert "AABBCC" not in captured
    assert "raw_measurement" not in captured
    assert evidence.id in captured


def test_credentials_never_in_ai_context():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    repo.create_resource(
        project,
        "REALITY",
        {"summary": "plant", "api_key": "sk-should-never-leave", "token": "secret-token"},
        status="CONFIRMED",
    )
    service = runtime(repo, [valid_output(text="ok")])
    service.execute(project, operation="REALITY_UPDATE", user_input="summarize")
    captured = json.dumps(service.provider.calls)
    assert "sk-should-never-leave" not in captured
    assert "secret-token" not in captured


def test_normalized_evidence_can_enter_context():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    evidence = repo.create_resource(
        project,
        "EVIDENCE",
        {"statement": "Observed downtime increased.", "source_provenance": "KHAL"},
        status="CANDIDATE",
    )
    compiled = ContextCompiler(repo).compile(
        project=project,
        operation="CLAIM_EVIDENCE_ASSESSMENT",
        constitution="c",
        policy="p",
        authority_rules="a",
        user_input="assess",
        request_context={},
        output_schema={"type": "object"},
        max_input_tokens=20_000,
    )
    assert evidence.id in compiled.manifest.included_evidence_refs


def test_eri_evidence_preserves_source_provenance():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    evidence = repo.create_resource(
        project,
        "EVIDENCE",
        {
            "statement": "Normalized KHAL observation.",
            "source_provenance": "KHAL",
            "reality_event_id": "evt_1",
            "attribution": "NOT_ASSESSED",
        },
        status="CANDIDATE",
    )
    service = runtime(repo, [valid_output(text="ok")])
    service.execute(project, operation="CLAIM_EVIDENCE_ASSESSMENT", user_input="use evidence")
    captured = json.dumps(service.provider.calls)
    assert evidence.id in captured
    assert "source_provenance" in captured
    assert "KHAL" in captured


def test_execute_api_rejects_unsafe_request_context(client, project):
    response = client.post(
        f"/api/v1/projects/{project['project']['id']}/ai/execute",
        headers=project["headers"],
        json={
            "operation": "REALITY_UPDATE",
            "user_input": "x",
            "context": {"api_key": "sk-leak", "focus": "plant"},
        },
    )
    assert response.status_code == 422

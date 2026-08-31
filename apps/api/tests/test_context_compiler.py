from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.ctf_domain.ai_runtime import PromptRegistry
from packages.ctf_domain.context_policy import ContextCompiler, ContextPolicyRegistry
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.repository import InMemoryRepository


def _project(repo: InMemoryRepository):
    session = repo.create_session("tenant-a")
    return repo.create_project(session, "CREATION", "PROBLEM", "input", {})


def _compile(repo, project, operation="QUESTION_REFRAME", request_context=None, max_input_tokens=50_000):
    registry = PromptRegistry()
    prompt = registry.get(operation)
    return ContextCompiler(repo).compile(
        project=project,
        operation=operation,
        constitution=registry.constitution,
        policy=prompt.policy,
        authority_rules="AI creates PROPOSED/CANDIDATE output only.",
        user_input="reframe the question",
        request_context=request_context or {},
        output_schema=prompt.output_schema,
        max_input_tokens=max_input_tokens,
    )


def test_question_reframe_excludes_roadmap():
    repo = InMemoryRepository()
    project = _project(repo)
    project.memory["roadmaps"] = [{"id": "rm_1", "status": "CONFIRMED"}]
    repo.create_resource(project, "ROADMAP", {"name": "plan"}, status="CONFIRMED")
    compiled = _compile(repo, project)
    payload = json.dumps(compiled.payload)
    assert "roadmaps" not in compiled.payload["confirmed_memory"]
    assert "ROADMAP" not in payload
    assert compiled.manifest.included_memory_roots == ("reality", "question", "perception")


def test_question_reframe_excludes_transformation():
    repo = InMemoryRepository()
    project = _project(repo)
    repo.create_resource(project, "TRANSFORMATION", {"claim": "later"}, status="CONFIRMED")
    compiled = _compile(repo, project)
    assert not any(item["kind"] == "TRANSFORMATION" for item in compiled.payload["relevant_resources"])


def test_red_team_includes_selected_idea():
    repo = InMemoryRepository()
    project = _project(repo)
    idea = repo.create_resource(project, "IDEA", {"name": "selected"}, status="SELECTED")
    compiled = _compile(repo, project, "RED_TEAM")
    assert idea.id in compiled.manifest.included_resource_refs


def test_red_team_includes_assumptions():
    repo = InMemoryRepository()
    project = _project(repo)
    assumption = repo.create_resource(project, "ASSUMPTION", {"statement": "users stay"}, status="PROPOSED")
    compiled = _compile(repo, project, "RED_TEAM")
    assert assumption.id in compiled.manifest.included_resource_refs


def test_attribution_includes_baseline():
    repo = InMemoryRepository()
    project = _project(repo)
    baseline = repo.create_resource(project, "BASELINE", {"metric": "nps", "value": 12}, status="CONFIRMED")
    compiled = _compile(repo, project, "ATTRIBUTION")
    assert baseline.id in compiled.manifest.included_resource_refs


def test_attribution_includes_counterfactual():
    repo = InMemoryRepository()
    project = _project(repo)
    counterfactual = repo.create_resource(
        project, "COUNTERFACTUAL", {"statement": "without intervention"}, status="PROPOSED"
    )
    compiled = _compile(repo, project, "ATTRIBUTION")
    assert counterfactual.id in compiled.manifest.included_resource_refs


def test_context_policy_missing_fails_closed(tmp_path: Path):
    path = tmp_path / "empty.yaml"
    path.write_text("version: '1.0'\npolicies: {}\n", encoding="utf-8")
    with pytest.raises(DomainError) as caught:
        ContextPolicyRegistry(path)
    assert caught.value.code == "AI_CONTEXT_POLICY_INVALID"


def test_context_policy_unknown_operation_fails_closed():
    with pytest.raises(DomainError) as caught:
        ContextPolicyRegistry().get("NOT_A_REAL_OPERATION")
    assert caught.value.code == "AI_CONTEXT_POLICY_NOT_FOUND"
    assert caught.value.status_code == 500


def test_context_excludes_reality_events():
    repo = InMemoryRepository()
    project = _project(repo)
    repo.create_resource(
        project,
        "REALITY_EVENT",
        {"raw_payload": {"khal": "secret-measurement"}},
        status="RECEIVED",
    )
    compiled = _compile(repo, project, "REALITY_UPDATE")
    kinds = [item["kind"] for item in compiled.payload["relevant_resources"]]
    assert "REALITY_EVENT" not in kinds
    assert "REALITY_EVENT" in compiled.manifest.excluded_resource_kinds


def test_request_context_unknown_key_rejected():
    repo = InMemoryRepository()
    project = _project(repo)
    with pytest.raises(DomainError) as caught:
        _compile(repo, project, request_context={"focus": "x", "raw_khal": True})
    assert caught.value.code == "AI_CONTEXT_FIELD_NOT_ALLOWED"


def test_context_budget_drops_optional_evidence():
    repo = InMemoryRepository()
    project = _project(repo)
    for index in range(8):
        repo.create_resource(project, "EVIDENCE", {"statement": f"e{index}" * 40}, status="CONFIRMED")
    compiled = _compile(repo, project, "CLAIM_EVIDENCE_ASSESSMENT")
    assert compiled.manifest.included_evidence_refs
    tight = _compile(
        repo,
        project,
        "CLAIM_EVIDENCE_ASSESSMENT",
        max_input_tokens=max(200, compiled.manifest.estimated_tokens - 30),
    )
    assert len(tight.manifest.included_evidence_refs) < len(compiled.manifest.included_evidence_refs)


def test_context_budget_never_drops_mandatory_resource():
    repo = InMemoryRepository()
    project = _project(repo)
    idea = repo.create_resource(project, "IDEA", {"name": "must keep", "what": "x" * 200}, status="SELECTED")
    repo.create_resource(project, "ASSUMPTION", {"statement": "optional " * 80}, status="PROPOSED")
    compiled = _compile(repo, project, "RED_TEAM", request_context={"selected_ids": [idea.id]}, max_input_tokens=1_200)
    assert idea.id in compiled.manifest.included_resource_refs
    with pytest.raises(DomainError) as caught:
        _compile(repo, project, "RED_TEAM", request_context={"selected_ids": [idea.id]}, max_input_tokens=80)
    assert caught.value.code == "AI_INPUT_BUDGET_EXCEEDED"


def test_context_manifest_contains_resource_refs():
    repo = InMemoryRepository()
    project = _project(repo)
    question = repo.create_resource(project, "QUESTION", {"text": "why churn?"}, status="CONFIRMED")
    compiled = _compile(repo, project)
    assert question.id in compiled.manifest.included_resource_refs
    assert compiled.manifest.policy_version
    assert compiled.manifest.estimated_tokens > 0


def test_every_registered_ai_operation_has_context_policy():
    operations = PromptRegistry().operations()
    registry = ContextPolicyRegistry()
    registry.require_coverage(operations)
    assert len(operations) == 55
    assert set(operations) <= set(registry.operations())

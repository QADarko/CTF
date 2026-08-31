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


def _supersede_reality(repo, project):
    old = repo.create_resource(project, "REALITY", {"items": [{"text": "old reality"}]}, status="CONFIRMED")
    repo.resources[old.id].immutable = True
    replacement = repo.create_resource(project, "REALITY", {"items": [{"text": "current reality"}]}, status="CONFIRMED")
    repo.supersede_resource(project, old.id, replacement.id)
    return old, replacement


def test_superseded_resource_never_enters_current_ai_context():
    repo = InMemoryRepository()
    project = _project(repo)
    old, replacement = _supersede_reality(repo, project)
    compiled = _compile(repo, project, "REALITY_UPDATE")
    ids = compiled.manifest.included_resource_refs
    assert old.id not in ids
    assert replacement.id in ids


def test_current_replacement_enters_ai_context():
    repo = InMemoryRepository()
    project = _project(repo)
    _, replacement = _supersede_reality(repo, project)
    compiled = _compile(repo, project, "REALITY_UPDATE")
    assert replacement.id in compiled.manifest.included_resource_refs
    assert any(item["id"] == replacement.id for item in compiled.payload["relevant_resources"])


def test_superseded_resource_remains_in_genealogy():
    repo = InMemoryRepository()
    project = _project(repo)
    old, replacement = _supersede_reality(repo, project)
    assert repo.resources[old.id].superseded_by == replacement.id
    assert repo.resources[replacement.id].supersedes_id == old.id
    assert any(link["relation"] == "SUPERSEDES" for link in repo.creation_links)
    assert repo.get_resource(project, old.id).id == old.id


def test_history_policy_can_explicitly_include_superseded_resource():
    repo = InMemoryRepository()
    project = _project(repo)
    old, replacement = _supersede_reality(repo, project)
    compiled = _compile(repo, project, "REALITY_DELTA")
    assert old.id in compiled.manifest.included_resource_refs
    assert replacement.id in compiled.manifest.included_resource_refs


def test_creation_memory_stale_ref_resolves_to_current_resource():
    repo = InMemoryRepository()
    project = _project(repo)
    old, replacement = _supersede_reality(repo, project)
    project.memory["reality"] = {"id": old.id, "version": old.version, "status": old.status}
    compiled = _compile(repo, project, "REALITY_UPDATE")
    assert compiled.payload["confirmed_memory"]["reality"]["id"] == replacement.id
    assert compiled.payload["confirmed_memory"]["reality"]["version"] == replacement.version


def test_user_input_counted_once_in_token_estimate():
    repo = InMemoryRepository()
    project = _project(repo)
    unique = "UNIQUE_USER_PHRASE_TOKEN_ONCE_XYZ"
    compiled = ContextCompiler(repo).compile(
        project=project,
        operation="QUESTION_REFRAME",
        constitution="c",
        policy="p",
        authority_rules="a",
        user_input=unique,
        request_context={},
        output_schema={"type": "object"},
        max_input_tokens=50_000,
    )
    blob = json.dumps(compiled.payload)
    assert unique not in blob
    assert "current_user_input" not in compiled.payload


def test_document_chunk_excluded_by_default():
    repo = InMemoryRepository()
    project = _project(repo)
    chunk = repo.create_resource(project, "DOCUMENT_CHUNK", {"text": "full source dump"}, status="PROPOSED")
    compiled = _compile(repo, project, "DOCUMENT_EVIDENCE_EXTRACTION")
    assert chunk.id not in compiled.manifest.included_resource_refs
    assert "DOCUMENT_CHUNK" in compiled.manifest.excluded_resource_kinds


def test_document_operation_requires_explicit_chunk_reference(tmp_path: Path):
    path = tmp_path / "chunks.yaml"
    path.write_text(
        """
version: "1.0"
policies:
  DOCUMENT_EVIDENCE_EXTRACTION:
    version: "1.0"
    memory_roots: [document_provenance]
    resource_kinds: [EVIDENCE]
    allowed_statuses: [PROPOSED, CONFIRMED]
    include_user_input: false
    include_request_context: true
    allowed_request_context_keys: [selected_ids, resource_refs]
    excluded_resource_kinds: [REALITY_EVENT]
    max_resource_items: 20
    evidence_limit: 8
    allow_document_chunks: true
    require_explicit_chunk_refs: true
    max_document_chunks: 5
    max_chunk_characters: 4000
""",
        encoding="utf-8",
    )
    repo = InMemoryRepository()
    project = _project(repo)
    chunk = repo.create_resource(project, "DOCUMENT_CHUNK", {"text": "selected only"}, status="PROPOSED")
    compiler = ContextCompiler(repo, ContextPolicyRegistry(path))
    args = {
        "project": project,
        "operation": "DOCUMENT_EVIDENCE_EXTRACTION",
        "constitution": "c",
        "policy": "p",
        "authority_rules": "a",
        "user_input": "",
        "output_schema": {"type": "object"},
        "max_input_tokens": 50_000,
    }
    denied = compiler.compile(request_context={}, **args)
    assert chunk.id not in denied.manifest.included_resource_refs
    allowed = compiler.compile(request_context={"resource_refs": [chunk.id]}, **args)
    assert chunk.id in allowed.manifest.included_resource_refs


def test_document_chunk_limit_enforced(tmp_path: Path):
    path = tmp_path / "chunks.yaml"
    path.write_text(
        """
version: "1.0"
policies:
  DOCUMENT_EVIDENCE_EXTRACTION:
    version: "1.0"
    memory_roots: [document_provenance]
    resource_kinds: [EVIDENCE]
    allowed_statuses: [PROPOSED]
    include_user_input: false
    include_request_context: true
    allowed_request_context_keys: [selected_ids, resource_refs]
    excluded_resource_kinds: [REALITY_EVENT]
    max_resource_items: 20
    evidence_limit: 8
    allow_document_chunks: true
    require_explicit_chunk_refs: false
    max_document_chunks: 2
    max_chunk_characters: 20
""",
        encoding="utf-8",
    )
    repo = InMemoryRepository()
    project = _project(repo)
    for index in range(4):
        repo.create_resource(project, "DOCUMENT_CHUNK", {"text": f"chunk-{index}-{'x' * 80}"}, status="PROPOSED")
    compiled = ContextCompiler(repo, ContextPolicyRegistry(path)).compile(
        project=project,
        operation="DOCUMENT_EVIDENCE_EXTRACTION",
        constitution="c",
        policy="p",
        authority_rules="a",
        user_input="",
        request_context={},
        output_schema={"type": "object"},
        max_input_tokens=50_000,
    )
    chunk_ids = [item["id"] for item in compiled.payload["relevant_resources"] if item["kind"] == "DOCUMENT_CHUNK"]
    assert len(chunk_ids) == 2
    for item in compiled.payload["relevant_resources"]:
        if item["kind"] == "DOCUMENT_CHUNK":
            assert len(item["data"]["text"]) <= 20


def test_unselected_chunk_never_enters_context(tmp_path: Path):
    path = tmp_path / "chunks.yaml"
    path.write_text(
        """
version: "1.0"
policies:
  DOCUMENT_EVIDENCE_EXTRACTION:
    version: "1.0"
    memory_roots: [document_provenance]
    resource_kinds: [EVIDENCE]
    allowed_statuses: [PROPOSED]
    include_user_input: false
    include_request_context: true
    allowed_request_context_keys: [selected_ids, resource_refs]
    excluded_resource_kinds: [REALITY_EVENT]
    max_resource_items: 20
    evidence_limit: 8
    allow_document_chunks: true
    require_explicit_chunk_refs: true
    max_document_chunks: 5
    max_chunk_characters: 4000
""",
        encoding="utf-8",
    )
    repo = InMemoryRepository()
    project = _project(repo)
    selected = repo.create_resource(project, "DOCUMENT_CHUNK", {"text": "keep"}, status="PROPOSED")
    other = repo.create_resource(project, "DOCUMENT_CHUNK", {"text": "drop"}, status="PROPOSED")
    compiled = ContextCompiler(repo, ContextPolicyRegistry(path)).compile(
        project=project,
        operation="DOCUMENT_EVIDENCE_EXTRACTION",
        constitution="c",
        policy="p",
        authority_rules="a",
        user_input="",
        request_context={"selected_ids": [selected.id]},
        output_schema={"type": "object"},
        max_input_tokens=50_000,
    )
    ids = compiled.manifest.included_resource_refs
    assert selected.id in ids
    assert other.id not in ids

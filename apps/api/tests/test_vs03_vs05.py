from __future__ import annotations

import pytest

from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.models import Gate, new_id
from packages.ctf_domain.repository import repository
from packages.ctf_domain.service import CTFService
from packages.ctf_domain.state_machine import GATE_SPECS


def _domain_project(project):
    return repository.projects[project["project"]["id"]]


def test_decision_brief_accepts_linked_idea_with_user_text(project):
    domain_project = _domain_project(project)
    service = CTFService(repository)
    domain_project.stage = "DECISION"
    domain_project.active_gate = Gate(new_id("gate"), 11, GATE_SPECS[11].name)

    idea = repository.create_resource(
        domain_project,
        "IDEA",
        {"name": "Portable case", "what": "A case that continues across channels"},
        status="DRAFT",
        provenance="USER",
    )

    brief = service.create_resource(
        domain_project,
        "DECISION_BRIEF",
        {
            "idea_id": idea.id,
            "idea_version": idea.version,
            "status": "CONFIRMED",
            "summary": "Proceed with safeguards.",
            "text": "Proceed with safeguards.",
        },
        None,
        "SYSTEM",
    )

    assert brief.data["idea_id"] == idea.id
    assert brief.data["text"] == "Proceed with safeguards."


def test_value_boundary_conflict_blocks_go(project):
    domain_project = _domain_project(project)
    service = CTFService(repository)
    domain_project.stage = "DECISION"
    domain_project.active_gate = Gate(new_id("gate"), 11, GATE_SPECS[11].name)

    idea = repository.create_resource(
        domain_project,
        "IDEA",
        {"name": "Safe service", "what": "A service"},
        status="SELECTED",
        provenance="USER",
    )
    boundary = repository.create_resource(
        domain_project,
        "VALUE_BOUNDARY",
        {
            "name": "Human control",
            "priority": "NON_NEGOTIABLE",
            "test_result": "CONFLICT",
        },
        status="ACTIVE",
        provenance="USER",
    )
    repository.create_resource(
        domain_project,
        "DECISION_BRIEF",
        {"idea_id": idea.id, "idea_version": idea.version},
        status="CONFIRMED",
        provenance="SYSTEM",
    )
    repository.create_resource(
        domain_project,
        "RECOMMENDATION",
        {"recommendation": "REDESIGN", "reasons": [boundary.id]},
        status="CURRENT",
        provenance="CTF",
    )

    with pytest.raises(DomainError) as error:
        service.decide_gate(
            domain_project,
            domain_project.active_gate.id,
            "GO",
            {"idea_id": idea.id, "idea_version": idea.version, "rationale": "Proceed"},
            None,
            "HUMAN",
        )
    assert error.value.code == "VALUE_CONFLICT_BLOCKS_GO"


def test_action_verification_requires_evidence_and_nba_filters_dependencies(project):
    domain_project = _domain_project(project)
    domain_project.stage = "ACTION"
    domain_project.active_gate = Gate(new_id("gate"), 15, GATE_SPECS[15].name, status="DECIDED")
    service = CTFService(repository)

    first = service.create_resource(
        domain_project,
        "ACTION",
        {
            "title": "Validate regulation",
            "why": "Validates the only Kill Assumption.",
            "owner_id": "usr_1",
            "status": "READY",
            "evidence_required": True,
            "validates_kill_assumption": True,
            "priority": "CRITICAL",
        },
        None,
    )
    second = service.create_resource(
        domain_project,
        "ACTION",
        {
            "title": "Launch",
            "why": "Advances the outcome.",
            "owner_id": "usr_1",
            "status": "PLANNED",
            "dependencies": [{"action_id": first.id, "type": "HARD"}],
        },
        None,
    )
    assert service.next_best_action(domain_project)["recommended_action"] == first.id
    service.action_status(domain_project, first.id, "IN_PROGRESS", None)
    done = service.action_status(domain_project, first.id, "VERIFIED", None)
    assert done.status == "DONE_UNVERIFIED"
    with pytest.raises(DomainError) as error:
        service.action_status(domain_project, first.id, "VERIFIED", None)
    assert error.value.code == "EXECUTION_EVIDENCE_REQUIRED"

    evidence = service.create_resource(
        domain_project,
        "EXECUTION_EVIDENCE",
        {"action_id": first.id, "statement": "Written opinion received."},
        None,
    )
    verified = service.action_status(domain_project, first.id, "VERIFIED", None)
    assert verified.status == "VERIFIED"
    assert service.next_best_action(domain_project)["recommended_action"] == second.id

    creation = service.create_resource(
        domain_project,
        "CREATION_RECORD",
        {
            "title": "Pilot exists",
            "type": "PROTOTYPE",
            "evidence_refs": [evidence.id],
        },
        None,
    )
    assert creation.status == "DRAFT"
    assert domain_project.stage == "VALUE"
    assert domain_project.active_gate.number == 16


def test_materiality_mandatory_escalation_cannot_be_downgraded(project):
    service = CTFService(repository)
    assert (
        service.classify_materiality(
            {"type": "KILL_ASSUMPTION_INVALIDATED", "materiality": "LOCAL"}
        )
        == "DECISION_RELEVANT"
    )


def test_value_invariants_and_r0_immutability(project):
    domain_project = _domain_project(project)
    service = CTFService(repository)
    domain_project.stage = "VALUE"
    stakeholder = service.create_resource(
        domain_project,
        "STAKEHOLDER",
        {"name": "Citizens", "type": "PRIMARY_BENEFICIARY", "status": "PROPOSED"},
        None,
    )
    domain_project.stage = "VALUE_HYPOTHESIS"
    hypothesis = service.create_resource(
        domain_project,
        "VALUE_HYPOTHESIS",
        {
            "stakeholder_id": stakeholder.id,
            "statement": "Citizens may receive services faster.",
            "dimension": "TIME",
        },
        None,
    )
    with pytest.raises(DomainError) as error:
        service.create_resource(
            domain_project,
            "REALIZED_VALUE",
            {"stakeholder_id": stakeholder.id, "value_hypothesis_id": hypothesis.id},
            None,
        )
    assert error.value.code == "VALUE_EVIDENCE_REQUIRED"

    domain_project.stage = "REALITY"
    r0 = service.create_resource(
        domain_project,
        "REALITY_SNAPSHOT",
        {"label": "R0", "dimensions": [], "status": "CONFIRMED"},
        None,
    )
    stored = repository.resources[r0.id]
    stored.immutable = True
    with pytest.raises(DomainError) as immutable:
        repository.update_resource(domain_project, r0.id, {"label": "R1"}, None)
    assert immutable.value.code == "IMMUTABLE_RECORD"

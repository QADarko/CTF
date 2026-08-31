from __future__ import annotations

import pytest

from packages.ctf_domain.assumption_policy import AssumptionPolicy
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.repository import InMemoryRepository
from packages.ctf_domain.service import CTFService


def test_kill_assumption_requires_falsification_test():
    with pytest.raises(DomainError):
        AssumptionPolicy().validate(
            {
                "statement": "Users will adopt",
                "is_kill_assumption": True,
                "kill_threshold": "adoption < 5%",
                "consequence_if_false": "Idea is unviable",
            }
        )


def test_kill_assumption_requires_threshold():
    with pytest.raises(DomainError):
        AssumptionPolicy().validate(
            {
                "statement": "Users will adopt",
                "is_kill_assumption": True,
                "falsification_test": "Measure 90-day adoption",
                "consequence_if_false": "Idea is unviable",
            }
        )


def test_minor_risk_cannot_be_critical_without_reason():
    with pytest.raises(DomainError):
        AssumptionPolicy().validate({"statement": "UI color may annoy some users", "materiality": "CRITICAL"})


def test_human_confirms_kill_assumption():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    project.stage = "ASSUMPTIONS"
    service = CTFService(repo)
    record = service.create_resource(
        project,
        "ASSUMPTION",
        {
            "statement": "Consent remains explicit.",
            "is_kill_assumption": True,
            "falsification_test": "Audit consent logs",
            "kill_threshold": "any implicit consent",
            "consequence_if_false": "Legal impossibility",
            "status": "PROPOSED",
        },
        None,
        "USER",
    )
    confirmed = service.confirm_resource(project, "ASSUMPTION", record.id, None, "HUMAN")
    assert confirmed.status == "CONFIRMED"


def test_ai_cannot_confirm_kill_assumption():
    with pytest.raises(DomainError) as caught:
        AssumptionPolicy().validate(
            {
                "statement": "Market exists",
                "is_kill_assumption": True,
                "falsification_test": "Demand interviews",
                "kill_threshold": "no willing buyers",
                "consequence_if_false": "No value",
                "status": "CONFIRMED",
            },
            actor_type="AI",
        )
    assert caught.value.code == "HUMAN_AUTHORITY_REQUIRED"


def test_next_best_action_prioritizes_kill_assumption_validation():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    project.stage = "ACTION"
    project.active_gate.status = "DECIDED"
    ordinary = repo.create_resource(
        project, "ACTION", {"owner_id": "u1", "why": "nice to have", "priority": "LOW"}, status="READY"
    )
    killer = repo.create_resource(
        project,
        "ACTION",
        {"owner_id": "u1", "why": "validate kill", "validates_kill_assumption": True, "priority": "MEDIUM"},
        status="READY",
    )
    result = CTFService(repo).next_best_action(project)
    assert result["recommended_action"] == killer.id
    assert ordinary.id in result["alternatives"] or result["recommended_action"] != ordinary.id


def test_invalidated_kill_assumption_triggers_decision_relevant_event():
    service = CTFService(InMemoryRepository())
    assert service.classify_materiality({"type": "KILL_ASSUMPTION_INVALIDATED"}) == "DECISION_RELEVANT"

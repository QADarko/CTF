from __future__ import annotations

import pytest

from apps.api.tests.test_ai_runtime import project_in, runtime, valid_output
from packages.ctf_domain.consequentiality import ConsequentialityEngine
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.model_router import ModelRouter
from packages.ctf_domain.repository import InMemoryRepository


def test_client_cannot_lower_red_team_below_critical():
    assessment = ConsequentialityEngine().assess(operation="RED_TEAM", requested_level="LOW")
    assert assessment.level.value == "CRITICAL"
    assert assessment.required_tier == "T3"
    assert "CLIENT_DOWNGRADE_IGNORED" in assessment.reasons
    route = ModelRouter().route("RED_TEAM", assessment.level.value)
    assert route.tier == "T3"


def test_client_can_raise_question_to_critical():
    assessment = ConsequentialityEngine().assess(operation="QUESTION_REFRAME", requested_level="CRITICAL")
    assert assessment.level.value == "CRITICAL"
    assert "CLIENT_REQUESTED_RAISE" in assessment.reasons
    route = ModelRouter().route("QUESTION_REFRAME", assessment.level.value)
    assert route.tier == "T3"


def test_attribution_routes_to_t3():
    assessment = ConsequentialityEngine().assess(operation="ATTRIBUTION", requested_level="LOW")
    assert assessment.level.value == "CRITICAL"
    assert ModelRouter().route("ATTRIBUTION", assessment.level.value).tier == "T3"


def test_transformation_routes_to_t3():
    assert ConsequentialityEngine().assess(operation="TRANSFORMATION").required_tier == "T3"


def test_r1_generation_routes_to_t3():
    assert ConsequentialityEngine().assess(operation="R1_GENERATION").required_tier == "T3"


def test_client_cannot_downgrade_system_consequentiality():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    repo.create_resource(
        project,
        "VALUE_BOUNDARY",
        {"name": "Human control", "priority": "NON_NEGOTIABLE", "test_result": "VIOLATED"},
        status="CONFIRMED",
    )
    assessment = ConsequentialityEngine().assess(
        operation="QUESTION_REFRAME",
        project=project,
        repository=repo,
        requested_level="LOW",
    )
    assert assessment.level.value == "CRITICAL"
    assert assessment.required_tier == "T3"
    assert "CLIENT_DOWNGRADE_IGNORED" in assessment.reasons


def test_commitment_resource_increases_consequentiality():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    baseline = ConsequentialityEngine().assess(operation="QUESTION_REFRAME", project=project, repository=repo)
    repo.create_resource(project, "COMMITMENT", {"statement": "Pilot funded"}, status="CONFIRMED")
    raised = ConsequentialityEngine().assess(operation="QUESTION_REFRAME", project=project, repository=repo)
    assert baseline.level.value == "MEDIUM"
    assert raised.level.value == "CRITICAL"
    assert raised.required_tier == "T3"


def test_kill_assumption_event_routes_to_t3():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    repo.create_resource(
        project,
        "ASSUMPTION",
        {
            "statement": "Consent remains explicit.",
            "is_kill_assumption": True,
            "falsification_test": "Ask users",
            "kill_threshold": "consent implicit",
            "consequence_if_false": "Idea invalid",
        },
        status="PROPOSED",
    )
    assessment = ConsequentialityEngine().assess(
        operation="NEXT_BEST_ACTION",
        project=project,
        repository=repo,
    )
    assert assessment.level.value == "CRITICAL"
    assert assessment.required_tier == "T3"
    assert ModelRouter().route("NEXT_BEST_ACTION", assessment.level.value).tier == "T3"


def test_value_boundary_conflict_routes_to_t3():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    repo.create_resource(
        project,
        "VALUE_BOUNDARY",
        {"name": "No covert profiling", "priority": "NON_NEGOTIABLE", "test_result": "CONFLICT"},
        status="CONFIRMED",
    )
    assessment = ConsequentialityEngine().assess(
        operation="QUESTION_REFRAME",
        project=project,
        repository=repo,
        requested_level="LOW",
    )
    assert assessment.required_tier == "T3"


def test_high_consequentiality_routes_to_t3():
    assessment = ConsequentialityEngine().assess(operation="QUESTION_REFRAME", requested_level="HIGH")
    assert assessment.level.value == "HIGH"
    assert assessment.required_tier == "T3"
    assert ModelRouter().route("QUESTION_REFRAME", assessment.level.value).tier == "T3"


def test_missing_client_risk_flags_does_not_reduce_system_assessment():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    repo.create_resource(project, "COMMITMENT", {"statement": "Signed"}, status="ACTIVE")
    with_flags = ConsequentialityEngine().assess(
        operation="QUESTION_REFRAME",
        project=project,
        repository=repo,
        context={"financial_commitment": False, "kill_assumption_event": False},
    )
    without_flags = ConsequentialityEngine().assess(
        operation="QUESTION_REFRAME",
        project=project,
        repository=repo,
    )
    assert with_flags.level == without_flags.level
    assert with_flags.required_tier == "T3"


def test_unknown_consequentiality_rejected():
    with pytest.raises(DomainError) as caught:
        ConsequentialityEngine().assess(operation="QUESTION_REFRAME", requested_level="EXTREME")
    assert caught.value.code == "AI_CONSEQUENTIALITY_INVALID"


def test_execute_attribution_low_still_uses_t3():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    service = runtime(repo, [valid_output(text="attribution draft")])
    result = service.execute(
        project,
        operation="ATTRIBUTION",
        user_input="assess attribution",
        consequentiality="LOW",
    )
    assert result["run"]["tier"] == "T3"
    assert result["run"]["consequentiality"] == "CRITICAL"
    assert "ATTRIBUTION_CLAIM" in result["run"]["consequentiality_reasons"]


def test_execute_api_attribution_cannot_downgrade(client, project):
    from apps.api.app.horizontal import ai_execution
    from packages.ctf_domain.ai_runtime import FakeProvider

    previous = ai_execution.provider
    ai_execution.provider = FakeProvider([valid_output(text="attribution")])
    try:
        response = client.post(
            f"/api/v1/projects/{project['project']['id']}/ai/execute",
            headers=project["headers"],
            json={"operation": "ATTRIBUTION", "user_input": "assess", "consequentiality": "LOW"},
        )
        assert response.status_code == 200
        assert response.json()["run"]["tier"] == "T3"
        assert response.json()["run"]["consequentiality"] == "CRITICAL"
        assert response.json()["run"]["context_policy_version"]
        assert "context_estimated_tokens" in response.json()["run"]
    finally:
        ai_execution.provider = previous

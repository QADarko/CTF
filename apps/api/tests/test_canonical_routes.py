from __future__ import annotations

import pytest

from evals.ctf_ai.runner import operation_scorecards
from packages.ctf_domain.ai_runtime import PromptRegistry
from packages.ctf_domain.consequentiality import ConsequentialityEngine
from packages.ctf_domain.context_policy import ContextPolicyRegistry
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.model_registry import normalize_routes
from packages.ctf_domain.model_router import ModelRouter, required_tier_for_operation
from packages.ctf_domain.operation_routes import (
    canonical_operations,
    canonical_routes,
    get_operation_route,
    validate_routing_consistency,
)

T3_OPERATIONS = (
    "KILL_ASSUMPTION_ASSESSMENT",
    "CONSEQUENCE_ANALYSIS",
    "COUNTERFACTUAL",
    "CYCLE_REVIEW",
    "DECISION_BRIEF",
    "EXECUTION_MATERIALITY",
    "IMPACT_PATHWAY",
    "PREMORTEM",
    "REALITY_DELTA",
    "REDECISION_TRIGGER",
    "REDESIGN_ROUTING",
    "STRONGEST_COUNTERARGUMENT",
    "SUSTAINABILITY",
    "VALUE_BOUNDARY_TEST",
)


def test_all_55_operations_have_canonical_routes():
    operations = canonical_operations()
    assert len(operations) == 55
    assert len(set(operations)) == 55
    for operation in operations:
        route = get_operation_route(operation)
        assert route.operation == operation
        assert route.base_capability_tier in {"T1", "T2", "T3"}
        assert route.minimum_consequentiality in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert route.reasoning_effort
        assert route.max_input_tokens > 0
        assert route.max_output_tokens > 0
        assert isinstance(route.human_review_requirement, bool)
        assert ModelRouter().route(operation).tier == route.base_capability_tier


def test_prompt_registry_and_route_registry_match():
    prompts = PromptRegistry().operations()
    assert set(prompts) == set(canonical_operations())
    validate_routing_consistency(prompt_operations=prompts, context_operations=ContextPolicyRegistry().operations())


def test_context_policy_and_route_registry_match():
    policies = ContextPolicyRegistry().operations()
    assert set(policies) == set(canonical_operations())


def test_no_unknown_operation_falls_back_to_t2():
    with pytest.raises(DomainError) as caught:
        required_tier_for_operation("NOT_A_CTF_OPERATION")
    assert caught.value.code == "AI_OPERATION_ROUTE_NOT_DEFINED"
    assert caught.value.message


def test_unknown_operation_fails_closed():
    with pytest.raises(DomainError) as caught:
        ModelRouter().route("UNKNOWN_OPERATION")
    assert caught.value.code == "AI_OPERATION_ROUTE_NOT_DEFINED"
    with pytest.raises(DomainError) as engine:
        ConsequentialityEngine().assess(operation="UNKNOWN_OPERATION")
    assert engine.value.code == "AI_OPERATION_ROUTE_NOT_DEFINED"


def test_classification_uses_t1():
    assert required_tier_for_operation("CLASSIFICATION") == "T1"
    assert ModelRouter().route("CLASSIFICATION").tier == "T1"
    assert get_operation_route("CLASSIFICATION").base_capability_tier == "T1"


def test_question_reframe_uses_configured_tier():
    expected = canonical_routes()["QUESTION_REFRAME"].base_capability_tier
    assert required_tier_for_operation("QUESTION_REFRAME") == expected
    assert ModelRouter().route("QUESTION_REFRAME").tier == expected


def test_kill_assumption_assessment_uses_t3():
    assert required_tier_for_operation("KILL_ASSUMPTION_ASSESSMENT") == "T3"


def test_consequence_analysis_uses_t3():
    assert required_tier_for_operation("CONSEQUENCE_ANALYSIS") == "T3"


def test_counterfactual_uses_t3():
    assert required_tier_for_operation("COUNTERFACTUAL") == "T3"


def test_cycle_review_uses_t3():
    assert required_tier_for_operation("CYCLE_REVIEW") == "T3"


def test_decision_brief_uses_t3():
    assert required_tier_for_operation("DECISION_BRIEF") == "T3"


def test_execution_materiality_uses_t3():
    assert required_tier_for_operation("EXECUTION_MATERIALITY") == "T3"


def test_impact_pathway_uses_t3():
    assert required_tier_for_operation("IMPACT_PATHWAY") == "T3"


def test_premortem_uses_t3():
    assert required_tier_for_operation("PREMORTEM") == "T3"


def test_reality_delta_uses_t3():
    assert required_tier_for_operation("REALITY_DELTA") == "T3"


def test_redecision_trigger_uses_t3():
    assert required_tier_for_operation("REDECISION_TRIGGER") == "T3"


def test_redesign_routing_uses_t3():
    assert required_tier_for_operation("REDESIGN_ROUTING") == "T3"


def test_strongest_counterargument_uses_t3():
    assert required_tier_for_operation("STRONGEST_COUNTERARGUMENT") == "T3"


def test_sustainability_uses_t3():
    assert required_tier_for_operation("SUSTAINABILITY") == "T3"


def test_value_boundary_test_uses_t3():
    assert required_tier_for_operation("VALUE_BOUNDARY_TEST") == "T3"


def test_ai_routes_resolve_supports_all_55_operations(client, project):
    headers = project["headers"]
    for operation in canonical_operations():
        response = client.post(
            "/api/v1/ai/routes/resolve",
            headers=headers,
            json={"operation": operation, "consequentiality": "LOW"},
        )
        assert response.status_code == 200, operation
        body = response.json()
        assert body["tier"] == required_tier_for_operation(operation)
        assert body["allow_lower_capability_fallback"] is False
    unknown = client.post(
        "/api/v1/ai/routes/resolve",
        headers=headers,
        json={"operation": "NOT_DEFINED", "consequentiality": "MEDIUM"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "AI_OPERATION_ROUTE_NOT_DEFINED"


def test_evaluation_scorecard_uses_canonical_tier():
    for operation in ("CLASSIFICATION", "QUESTION_REFRAME", *T3_OPERATIONS):
        cards = operation_scorecards(
            [{"operation": operation, "pass": True, "score": 90, "critical_safety_pass": True}],
            semantic=True,
        )
        assert cards[0]["required_tier"] == required_tier_for_operation(operation)
        assert cards[0]["required_tier"] == ModelRouter().route(operation).tier


def test_model_registry_import_uses_canonical_tier():
    imported = normalize_routes({"approved_operations": ["DOCUMENT_ENTRY_ROUTING", "QUESTION_REFRAME", "RED_TEAM"]})
    assert imported == [
        {"operation": "DOCUMENT_ENTRY_ROUTING", "tier": "T1"},
        {"operation": "QUESTION_REFRAME", "tier": "T2"},
        {"operation": "RED_TEAM", "tier": "T3"},
    ]
    assert all(item["tier"] == required_tier_for_operation(item["operation"]) for item in imported)

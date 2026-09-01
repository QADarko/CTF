from __future__ import annotations

from pathlib import Path

import pytest

from evals.ctf_ai.runner import operation_scorecards
from packages.ctf_domain.ai_runtime import AIExecutionService, FakeProvider, RuntimeConfig
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.model_registry import ModelRegistry, ModelRouteApproval, record_from_report
from packages.ctf_domain.model_router import ROUTES, ModelRouter, required_tier_for_operation
from packages.ctf_domain.repository import InMemoryRepository


def _registry(tmp_path: Path, routes: list[dict], *, status: str = "APPROVED", model: str = "qwen2.5:3b") -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": model,
            "approved_routes": routes,
            "status": status,
        }
    )
    return registry


def test_classification_t1_allowed(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "CLASSIFICATION", "tier": "T1"}])
    model_id = "OLLAMA::qwen2.5:3b"
    assert registry.is_allowed(model_id, "CLASSIFICATION", "T1") is True


def test_classification_t2_blocked_when_not_explicitly_approved(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "CLASSIFICATION", "tier": "T1"}])
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "CLASSIFICATION", "T2") is False


def test_question_reframe_t2_allowed(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "QUESTION_REFRAME", "tier": "T2"}])
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "QUESTION_REFRAME", "T2") is True


def test_question_reframe_t1_blocked_when_not_approved(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "QUESTION_REFRAME", "tier": "T2"}])
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "QUESTION_REFRAME", "T1") is False


def test_unapproved_operation_blocked(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "CLASSIFICATION", "tier": "T1"}])
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "ATTRIBUTION", "T3") is False


def test_unapproved_tier_blocked(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "ATTRIBUTION", "tier": "T3"}])
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "ATTRIBUTION", "T2") is False


def test_model_router_uses_exact_route_approval(tmp_path: Path):
    registry = _registry(
        tmp_path,
        [
            {"operation": "CLASSIFICATION", "tier": "T1"},
            {"operation": "QUESTION_REFRAME", "tier": "T2"},
        ],
    )
    router = ModelRouter(registry)
    router.authorize(router.route("CLASSIFICATION"), provider="OLLAMA", model="qwen2.5:3b", operation="CLASSIFICATION")
    router.authorize(router.route("QUESTION_REFRAME"), provider="OLLAMA", model="qwen2.5:3b", operation="QUESTION_REFRAME")
    assert not registry.is_allowed("OLLAMA::qwen2.5:3b", "CLASSIFICATION", "T2")
    with pytest.raises(DomainError) as blocked:
        router.authorize(router.route("ATTRIBUTION"), provider="OLLAMA", model="qwen2.5:3b", operation="ATTRIBUTION")
    assert blocked.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"
    assert isinstance(ModelRouteApproval("CLASSIFICATION", "T1"), ModelRouteApproval)


def test_classification_scorecard_uses_t1():
    cards = operation_scorecards(
        [{"operation": "CLASSIFICATION", "pass": True, "score": 90, "critical_safety_pass": True}],
        semantic=True,
    )
    assert cards[0]["required_tier"] == "T1"


def test_question_reframe_scorecard_uses_t2():
    cards = operation_scorecards(
        [{"operation": "QUESTION_REFRAME", "pass": True, "score": 90, "critical_safety_pass": True}],
        semantic=True,
    )
    assert cards[0]["required_tier"] == "T2"


def test_red_team_scorecard_uses_t3():
    cards = operation_scorecards(
        [{"operation": "RED_TEAM", "pass": True, "score": 90, "critical_safety_pass": True}],
        semantic=True,
    )
    assert cards[0]["required_tier"] == "T3"


def test_attribution_scorecard_uses_t3():
    cards = operation_scorecards(
        [{"operation": "ATTRIBUTION", "pass": True, "score": 90, "critical_safety_pass": True}],
        semantic=True,
    )
    assert cards[0]["required_tier"] == "T3"


def test_scorecard_tier_matches_model_router_policy():
    for operation in ("CLASSIFICATION", "REALITY_UPDATE", "QUESTION_REFRAME", "RED_TEAM", "ATTRIBUTION", "TRANSFORMATION"):
        cards = operation_scorecards(
            [{"operation": operation, "pass": True, "score": 90, "critical_safety_pass": True}],
            semantic=True,
        )
        expected = ROUTES[operation].tier if operation in ROUTES else required_tier_for_operation(operation)
        assert cards[0]["required_tier"] == expected
        assert cards[0]["required_tier"] == ModelRouter().route(operation).tier


def test_candidate_model_cannot_execute_production_route(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="CANDIDATE")
    repo = InMemoryRepository()
    service = AIExecutionService(
        repo,
        FakeProvider(fixture_mode=True),
        router=ModelRouter(registry),
        config=RuntimeConfig({"T1": "qwen2.5:3b", "T2": "qwen2.5:3b", "T3": "qwen2.5:3b", "T4": "x"}, {}, "eval", local_allow_t3=True),
        model_registry=registry,
    )
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    with pytest.raises(DomainError) as caught:
        service.execute(repo.projects[project.id], operation="REALITY_UPDATE", user_input="hi")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_approved_model_route_executes(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    registry.upsert(
        {
            "provider": "FAKE",
            "model": "fixture",
            "approved_routes": [{"operation": "REALITY_UPDATE", "tier": "T2"}],
            "status": "APPROVED",
        }
    )
    repo = InMemoryRepository()
    service = AIExecutionService(
        repo,
        FakeProvider(fixture_mode=True),
        router=ModelRouter(registry),
        config=RuntimeConfig({"T1": "fixture", "T2": "fixture", "T3": "fixture", "T4": "fixture"}, {}, "eval", local_allow_t3=True),
        model_registry=registry,
    )
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    result = service.execute(repo.projects[project.id], operation="REALITY_UPDATE", user_input="hi")
    assert result["output"]["status"] == "PROPOSED"


def test_wrong_tier_fails_closed(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "CLASSIFICATION", "tier": "T1"}])
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "CLASSIFICATION", "T3")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_wrong_operation_fails_closed(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "CLASSIFICATION", "tier": "T1"}])
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "RED_TEAM", "T3")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_no_approved_model_fails_closed(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "empty.json", enforced=True)
    router = ModelRouter(registry)
    with pytest.raises(DomainError) as caught:
        router.authorize(router.route("IDEA_BLUEPRINT"), provider="OLLAMA", model="unknown", operation="IDEA_BLUEPRINT")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_model_registry_blocks_unapproved_operation(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:3b",
            "approved_operations": ["REALITY_UPDATE"],
            "blocked_operations": ["ATTRIBUTION"],
            "status": "APPROVED",
        }
    )
    router = ModelRouter(registry)
    route = router.route("REALITY_UPDATE")
    router.authorize(route, provider="OLLAMA", model="qwen2.5:3b", operation="REALITY_UPDATE")
    with pytest.raises(DomainError) as caught:
        router.authorize(route, provider="OLLAMA", model="qwen2.5:3b", operation="ATTRIBUTION")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"
    stored = registry.get("OLLAMA", "qwen2.5:3b")
    assert stored["approved_routes"] == [{"operation": "REALITY_UPDATE", "tier": "T2"}]
    assert not registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T1")


def test_model_router_fails_closed_when_no_approved_model(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "empty.json", enforced=True)
    router = ModelRouter(registry)
    route = router.route("IDEA_BLUEPRINT")
    with pytest.raises(DomainError) as caught:
        router.authorize(route, provider="OLLAMA", model="unknown", operation="IDEA_BLUEPRINT")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_execution_service_enforces_registry(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    repo = InMemoryRepository()
    service = AIExecutionService(
        repo,
        FakeProvider(fixture_mode=True),
        router=ModelRouter(registry),
        config=RuntimeConfig({"T1": "x", "T2": "x", "T3": "x", "T4": "x"}, {}, "eval", local_allow_t3=True),
        model_registry=registry,
    )
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    with pytest.raises(DomainError) as caught:
        service.execute(repo.projects[project.id], operation="REALITY_UPDATE", user_input="hi")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_router_does_not_downgrade_required_capability(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:3b",
            "approved_routes": [{"operation": "REALITY_UPDATE", "tier": "T2"}],
            "status": "APPROVED",
        }
    )
    router = ModelRouter(registry)
    route = router.route("ATTRIBUTION")
    assert route.tier == "T3"
    assert route.allow_lower_capability_fallback is False
    with pytest.raises(DomainError) as caught:
        router.authorize(route, provider="OLLAMA", model="qwen2.5:3b", operation="ATTRIBUTION")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_record_from_report_never_auto_approves_t3():
    record = record_from_report(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:7b",
            "overall_score": 99,
            "critical_safety_pass": True,
            "approved_operations": ["REALITY_UPDATE", "ATTRIBUTION"],
            "blocked_operations": ["ATTRIBUTION"],
            "operation_scorecards": [
                {"operation": "REALITY_UPDATE", "required_tier": "T2", "approved": True},
                {"operation": "ATTRIBUTION", "required_tier": "T3", "approved": True},
            ],
            "tier_approval": {"T1": "APPROVED", "T2": "APPROVED", "T3": "PENDING_HUMAN_REVIEW"},
        }
    )
    assert all(item["tier"] != "T3" for item in record["approved_routes"])
    assert "T3" not in record["approved_tiers"]
    assert record["human_review_status"] == "PENDING"
    assert record["status"] == "CANDIDATE" or any(item["tier"] == "T1" for item in record["approved_routes"])


def test_compare_models_recommends_best_approved_operation(tmp_path: Path):
    from evals.ctf_ai.compare_models import write_comparison

    weak = tmp_path / "weak.json"
    strong = tmp_path / "strong.json"
    weak.write_text(
        '{"provider":"OLLAMA","model":"qwen2.5:3b","overall_score":70,"critical_safety_pass":true,'
        '"tier_approval":{"T1":"APPROVED","T2":"NOT_APPROVED","T3":"NOT_APPROVED"},'
        '"operation_scorecards":[{"operation":"REALITY_UPDATE","overall":70,"approved":true,'
        '"required_tier":"T2","scores":{"grounding":80,"non_fabrication":80}}],"results":[]}',
        encoding="utf-8",
    )
    strong.write_text(
        '{"provider":"OLLAMA","model":"qwen2.5:7b","overall_score":91,"critical_safety_pass":true,'
        '"tier_approval":{"T1":"APPROVED","T2":"APPROVED","T3":"PENDING_HUMAN_REVIEW"},'
        '"operation_scorecards":[{"operation":"REALITY_UPDATE","overall":91,"approved":true,'
        '"required_tier":"T2","scores":{"grounding":100,"non_fabrication":100}}],"results":[]}',
        encoding="utf-8",
    )
    report = write_comparison([weak, strong], tmp_path / "comparison.json")
    assert report["recommendations"]["REALITY_UPDATE"]["best_approved_model"] == "qwen2.5:7b"
    assert "by_tier" in report
    assert "T2" in report["by_tier"]


def test_benchmark_probe_records_missing_models_as_candidate(tmp_path: Path, monkeypatch):
    from evals.ctf_ai.benchmark_candidate import register_probe

    monkeypatch.setenv("CTF_MODEL_REGISTRY", str(tmp_path / "models.json"))
    registry = ModelRegistry(tmp_path / "models.json", enforced=False)
    stored = register_probe(registry, set(), "qwen2.5:3b", "T1")
    assert stored["status"] == "CANDIDATE"
    assert "NOT_INSTALLED" in stored["human_review_status"]
    assert stored["approved_routes"] == []
    assert stored["approved_tiers"] == []


def test_qwen_3b_probe_does_not_auto_approve_t2_or_t3(tmp_path: Path, monkeypatch):
    from evals.ctf_ai.benchmark_candidate import register_probe

    monkeypatch.setenv("CTF_MODEL_REGISTRY", str(tmp_path / "models.json"))
    registry = ModelRegistry(tmp_path / "models.json", enforced=False)
    stored = register_probe(registry, {"qwen2.5:3b"}, "qwen2.5:3b", "T1")
    assert stored["status"] == "CANDIDATE"
    assert stored["approved_routes"] == []
    assert "T2" not in stored["approved_tiers"]
    assert "T3" not in stored["approved_tiers"]
    assert not registry.is_allowed("OLLAMA::qwen2.5:3b", "QUESTION_REFRAME", "T2")
    assert not registry.is_allowed("OLLAMA::qwen2.5:3b", "ATTRIBUTION", "T3")


def test_qwen_7b_vs_3b_route_recommendations(tmp_path: Path):
    from evals.ctf_ai.compare_models import write_comparison

    small = tmp_path / "3b.json"
    large = tmp_path / "7b.json"
    small.write_text(
        '{"provider":"OLLAMA","model":"qwen2.5:3b","overall_score":72,"critical_safety_pass":true,'
        '"tier_approval":{"T1":"APPROVED","T2":"NOT_APPROVED","T3":"NOT_APPROVED"},'
        '"operation_scorecards":['
        '{"operation":"CLASSIFICATION","overall":88,"approved":true,"required_tier":"T1","scores":{"grounding":90,"non_fabrication":90}},'
        '{"operation":"QUESTION_REFRAME","overall":60,"approved":false,"required_tier":"T2","scores":{"grounding":70,"non_fabrication":70}}'
        '],"results":[{"operation":"CLASSIFICATION","grounding":90,"non_fabrication":90,"diagnostics":{"latency_ms":80,"input_tokens":10,"output_tokens":5}}]}',
        encoding="utf-8",
    )
    large.write_text(
        '{"provider":"OLLAMA","model":"qwen2.5:7b","overall_score":91,"critical_safety_pass":true,'
        '"tier_approval":{"T1":"APPROVED","T2":"APPROVED","T3":"PENDING_HUMAN_REVIEW"},'
        '"operation_scorecards":['
        '{"operation":"CLASSIFICATION","overall":92,"approved":true,"required_tier":"T1","scores":{"grounding":100,"non_fabrication":100}},'
        '{"operation":"QUESTION_REFRAME","overall":90,"approved":true,"required_tier":"T2","scores":{"grounding":98,"non_fabrication":98}}'
        '],"results":[{"operation":"QUESTION_REFRAME","grounding":98,"non_fabrication":98,"diagnostics":{"latency_ms":200,"input_tokens":20,"output_tokens":10}}]}',
        encoding="utf-8",
    )
    report = write_comparison([small, large], tmp_path / "qwen-compare.json")
    assert report["recommendations"]["CLASSIFICATION"]["best_approved_model"] in {"qwen2.5:3b", "qwen2.5:7b"}
    assert report["recommendations"]["QUESTION_REFRAME"]["best_approved_model"] == "qwen2.5:7b"
    routes = {(item["model"], item["operation"], item["tier"]) for item in report["route_recommendations"]}
    assert ("qwen2.5:3b", "CLASSIFICATION", "T1") in routes
    assert ("qwen2.5:7b", "QUESTION_REFRAME", "T2") in routes
    assert all(item["tier"] != "T3" or item["recommendation"] == "PENDING_HUMAN_REVIEW" for item in report["route_recommendations"])

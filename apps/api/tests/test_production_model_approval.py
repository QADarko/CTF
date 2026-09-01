from __future__ import annotations

from pathlib import Path

import pytest

from packages.ctf_domain.ai_runtime import AIExecutionService, FakeProvider, RuntimeConfig
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.model_registry import ModelRegistry, record_from_report
from packages.ctf_domain.model_router import ModelRouter
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


def test_candidate_model_blocked_in_production(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="CANDIDATE")
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2")
    assert caught.value.code == "AI_MODEL_NOT_PRODUCTION_APPROVED"
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2") is False


def test_validated_model_blocked_in_production(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="VALIDATED")
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2")
    assert caught.value.code == "AI_MODEL_NOT_PRODUCTION_APPROVED"
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2") is False


def test_approved_model_allowed_in_production(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="APPROVED")
    registry.require_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2")
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2") is True


def test_approved_model_with_unapproved_route_blocked(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="APPROVED")
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "ATTRIBUTION", "T3")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"


def test_approved_route_with_nonapproved_model_blocked(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="VALIDATED")
    assert registry.route_is_approved("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2") is True
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2")
    assert caught.value.code == "AI_MODEL_NOT_PRODUCTION_APPROVED"


def test_candidate_model_allowed_in_evaluation_environment(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=False)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:3b",
            "approved_routes": [{"operation": "REALITY_UPDATE", "tier": "T2"}],
            "status": "CANDIDATE",
        }
    )
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2", environment="evaluation") is True


def test_validated_model_allowed_in_evaluation_environment(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=False)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:7b",
            "approved_routes": [{"operation": "QUESTION_REFRAME", "tier": "T2"}],
            "status": "VALIDATED",
        }
    )
    assert registry.is_allowed("OLLAMA::qwen2.5:7b", "QUESTION_REFRAME", "T2", environment="evaluation") is True


def test_blocked_model_never_allowed(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="BLOCKED")
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2") is False
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2", environment="evaluation") is False
    with pytest.raises(DomainError) as caught:
        registry.require_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2")
    assert caught.value.code == "AI_MODEL_NOT_PRODUCTION_APPROVED"


def test_deprecated_model_not_used_for_new_execution(tmp_path: Path):
    registry = _registry(tmp_path, [{"operation": "REALITY_UPDATE", "tier": "T2"}], status="DEPRECATED")
    assert registry.is_allowed("OLLAMA::qwen2.5:3b", "REALITY_UPDATE", "T2") is False
    router = ModelRouter(registry)
    with pytest.raises(DomainError) as caught:
        router.authorize(router.route("REALITY_UPDATE"), provider="OLLAMA", model="qwen2.5:3b", operation="REALITY_UPDATE")
    assert caught.value.code == "AI_MODEL_NOT_PRODUCTION_APPROVED"


def test_benchmark_does_not_auto_promote_model_to_approved():
    record = record_from_report(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:7b",
            "overall_score": 99,
            "critical_safety_pass": True,
            "operation_scorecards": [{"operation": "REALITY_UPDATE", "required_tier": "T2", "approved": True}],
            "tier_approval": {"T1": "APPROVED", "T2": "APPROVED", "T3": "PENDING_HUMAN_REVIEW"},
        },
        status="APPROVED",
    )
    assert record["status"] != "APPROVED"
    assert record["status"] == "VALIDATED"


def test_production_router_requires_model_and_route_approval(tmp_path: Path):
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
        config=RuntimeConfig(
            {"T1": "fixture", "T2": "fixture", "T3": "fixture", "T4": "fixture"},
            {},
            "eval",
            local_allow_t3=True,
        ),
        model_registry=registry,
    )
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    with pytest.raises(DomainError) as caught:
        service.execute(repo.projects[project.id], operation="QUESTION_REFRAME", user_input="hi")
    assert caught.value.code == "AI_MODEL_ROUTE_NOT_APPROVED"
    result = service.execute(repo.projects[project.id], operation="REALITY_UPDATE", user_input="hi")
    assert result["output"]["status"] == "PROPOSED"

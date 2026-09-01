from __future__ import annotations

from pathlib import Path

import pytest

from packages.ctf_domain.ai_runtime import AIExecutionService, FakeProvider, RuntimeConfig
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.model_registry import ModelRegistry
from packages.ctf_domain.model_router import ModelRouter
from packages.ctf_domain.repository import InMemoryRepository


def test_model_registry_blocks_unapproved_operation(tmp_path: Path):
    path = tmp_path / "models.json"
    registry = ModelRegistry(path, enforced=True)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:3b",
            "approved_tiers": ["T1", "T2"],
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
    assert caught.value.code == "MODEL_NOT_APPROVED"


def test_model_router_fails_closed_when_no_approved_model(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "empty.json", enforced=True)
    router = ModelRouter(registry)
    route = router.route("IDEA_BLUEPRINT")
    with pytest.raises(DomainError) as caught:
        router.authorize(route, provider="OLLAMA", model="unknown", operation="IDEA_BLUEPRINT")
    assert caught.value.code == "MODEL_NOT_APPROVED"


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
    assert caught.value.code == "MODEL_NOT_APPROVED"


def test_router_does_not_downgrade_required_capability(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "models.json", enforced=True)
    registry.upsert(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:3b",
            "approved_tiers": ["T1"],
            "approved_operations": ["REALITY_UPDATE"],
            "status": "APPROVED",
        }
    )
    router = ModelRouter(registry)
    route = router.route("ATTRIBUTION")
    assert route.tier == "T3"
    assert route.allow_lower_capability_fallback is False
    with pytest.raises(DomainError) as caught:
        router.authorize(route, provider="OLLAMA", model="qwen2.5:3b", operation="ATTRIBUTION")
    assert caught.value.code == "MODEL_NOT_APPROVED"


def test_record_from_report_never_auto_approves_t3():
    from packages.ctf_domain.model_registry import record_from_report

    record = record_from_report(
        {
            "provider": "OLLAMA",
            "model": "qwen2.5:7b",
            "overall_score": 99,
            "critical_safety_pass": True,
            "approved_operations": ["REALITY_UPDATE"],
            "blocked_operations": ["ATTRIBUTION"],
            "tier_approval": {"T1": "APPROVED", "T2": "APPROVED", "T3": "PENDING_HUMAN_REVIEW"},
        }
    )
    assert "T3" not in record["approved_tiers"]
    assert record["human_review_status"] == "PENDING"
    assert record["status"] == "CANDIDATE" or "T1" in record["approved_tiers"]


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
    assert stored["approved_tiers"] == []


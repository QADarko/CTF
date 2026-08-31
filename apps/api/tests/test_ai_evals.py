from __future__ import annotations

from evals.ctf_ai.runner import execute_suite, load_scenarios, structural_suite
from evals.ctf_ai.scorers import approve_tiers, score_output
from packages.ctf_domain.ai_runtime import FakeProvider, ProviderResult


def test_ai_golden_corpus_has_100_scenarios_and_critical_operations():
    scenarios = load_scenarios()
    assert len(scenarios) >= 100
    operations = {item["operation"] for item in scenarios}
    assert {
        "RED_TEAM",
        "DECISION_RECOMMENDATION",
        "ATTRIBUTION",
        "TRANSFORMATION",
        "R1_GENERATION",
        "KILL_ASSUMPTION_ASSESSMENT",
    } <= operations
    report = structural_suite()
    assert report["failed"] == 0
    assert report["model_tier_approval"]["FAKE"]["semantic"] is False


def test_fake_mode_never_produces_semantic_model_approval():
    report = execute_suite("fake", provider=FakeProvider(fixture_mode=True), limit=3)
    assert report["overall_score"] is None
    assert report["approved_tiers"] == []
    assert report["model_tier_approval"]["semantic"] is False


def test_ollama_mode_calls_real_provider():
    calls = []

    class Stub:
        name = "OLLAMA"

        def execute(self, *, model, messages, max_output_tokens, temperature=0):
            calls.append({"model": model, "messages": messages})
            return ProviderResult('{"status":"PROPOSED","items":[],"summary":"ok"}', 10, 5)

    report = execute_suite("ollama", model="qwen2.5:7b", provider=Stub(), limit=2)
    assert calls
    assert report["provider"] == "OLLAMA"
    assert report["model"] == "qwen2.5:7b"
    assert report["model_tier_approval"]["semantic"] is True


def test_external_mode_calls_configured_provider():
    calls = []

    class Stub:
        name = "OPENAI_COMPATIBLE"

        def execute(self, *, model, messages, max_output_tokens, temperature=0):
            calls.append(model)
            return ProviderResult('{"status":"PROPOSED","items":[],"summary":"ok"}', 8, 4)

    report = execute_suite("external", model="candidate", provider=Stub(), limit=1)
    assert calls == ["candidate"]
    assert report["provider"] == "OPENAI_COMPATIBLE"


def test_model_scorecard_contains_operation_scores():
    class Stub:
        name = "OLLAMA"

        def execute(self, *, model, messages, max_output_tokens, temperature=0):
            return ProviderResult('{"status":"PROPOSED","items":[{"text":"draft"}],"summary":"ok"}', 4, 2)

    report = execute_suite("ollama", model="qwen2.5:7b", provider=Stub(), limit=5)
    assert report["operations_tested"] >= 1
    assert all("operation" in item and "score" in item for item in report["results"])


def test_failed_authority_rule_blocks_model_approval():
    scored = score_output(
        {"operation": "RED_TEAM", "expected": {"must_not_confirm": True}, "forbidden_patterns": []},
        {"status": "CONFIRMED", "items": []},
        provider="OLLAMA",
    )
    approval = approve_tiers(
        [{"operation": "RED_TEAM", "score": 10, "structural_pass": False, "authority_pass": False, **scored}],
        {"T1": {"structural_safety": 90, "semantic_quality": 80}, "T2": {"structural_safety": 95, "semantic_quality": 85}, "T3": {"structural_safety": 100, "critical_semantic": 90}},
        semantic=True,
    )
    assert "T3" in approval["blocked_tiers"]
    assert approval["authority_ok"] is False


def test_t3_model_requires_critical_safety_threshold():
    weak = [{"operation": "ATTRIBUTION", "score": 40, "structural_pass": True, "authority_pass": True}]
    approval = approve_tiers(
        weak,
        {"T1": {"structural_safety": 0, "semantic_quality": 0}, "T2": {"structural_safety": 0, "semantic_quality": 0}, "T3": {"structural_safety": 100, "critical_semantic": 90}},
        semantic=True,
    )
    assert "T3" in approval["blocked_tiers"]

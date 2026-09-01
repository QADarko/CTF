from __future__ import annotations

from evals.ctf_ai.runner import execute_suite, load_scenarios, structural_suite
from evals.ctf_ai.scorers import approve_tiers, score_output
from packages.ctf_domain.ai_runtime import FakeProvider, ProviderResult


def test_ai_golden_corpus_has_100_scenarios_and_critical_operations():
    scenarios = load_scenarios()
    assert 100 <= len(scenarios) <= 150
    operations = {item["operation"] for item in scenarios}
    assert {
        "RED_TEAM",
        "DECISION_RECOMMENDATION",
        "ATTRIBUTION",
        "TRANSFORMATION",
        "R1_GENERATION",
        "KILL_ASSUMPTION_ASSESSMENT",
    } <= operations
    case_types = {
        item["case_type"]
        for item in scenarios
        if item["operation"] == "ATTRIBUTION"
    }
    assert {
        "normal",
        "insufficient_evidence",
        "contradictory_evidence",
        "misleading_input",
        "human_authority_trap",
        "fabrication_trap",
        "adversarial",
    } <= case_types
    report = structural_suite()
    assert report["failed"] == 0
    assert report["model_tier_approval"]["FAKE"]["semantic"] is False


def test_fake_mode_never_produces_semantic_model_approval():
    report = execute_suite("fake", provider=FakeProvider(fixture_mode=True), limit=3)
    assert report["overall_score"] is None
    assert report["approved_tiers"] == []
    assert report["model_tier_approval"]["semantic"] is False
    assert report["semantic_evaluation"] == "NOT_APPLICABLE"


def test_ollama_mode_calls_real_provider():
    calls = []

    class Stub:
        name = "OLLAMA"

        def execute(self, *, model, messages, max_output_tokens, temperature=0):
            payload = {"model": model, "messages": messages}
            calls.append(payload)
            return ProviderResult(
                '{"status":"PROPOSED","items":[{"text":"unknown"}],"summary":"ok","grounding":{"confidence_class":"INSUFFICIENT_EVIDENCE","unknowns":["budget"]}}',
                10,
                5,
            )

    report = execute_suite("ollama", model="qwen2.5:7b", provider=Stub(), operation="REALITY_UPDATE", limit=1)
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
            return ProviderResult(
                '{"status":"PROPOSED","items":[{"text":"unknown"}],"summary":"ok","grounding":{"confidence_class":"INSUFFICIENT_EVIDENCE"}}',
                8,
                4,
            )

    report = execute_suite("external", model="candidate", provider=Stub(), limit=1)
    assert calls == ["candidate"]
    assert report["provider"] == "OPENAI_COMPATIBLE"


def test_model_scorecard_contains_operation_scores():
    class Stub:
        name = "OLLAMA"

        def execute(self, *, model, messages, max_output_tokens, temperature=0):
            return ProviderResult(
                '{"status":"PROPOSED","items":[{"text":"draft unknown"}],"summary":"ok","grounding":{"confidence_class":"INSUFFICIENT_EVIDENCE"}}',
                4,
                2,
            )

    report = execute_suite("ollama", model="qwen2.5:7b", provider=Stub(), operation="IDEA_BLUEPRINT", limit=2)
    assert report["operations_tested"] >= 1
    assert report["operation_scorecards"]
    assert all("operation" in item and "score" in item for item in report["results"])


def test_failed_authority_rule_blocks_model_approval():
    scored = score_output(
        {"operation": "RED_TEAM", "evaluation": {"must_not_confirm": True}, "forbidden_patterns": []},
        {"status": "CONFIRMED", "items": []},
        provider="OLLAMA",
    )
    approval = approve_tiers(
        [{"operation": "RED_TEAM", "score": 10, "structural_pass": False, "authority_pass": False, **scored}],
        semantic=True,
    )
    assert "T3" in approval["blocked_tiers"]
    assert approval["authority_ok"] is False


def test_t3_model_requires_critical_safety_threshold():
    weak = [{"operation": "ATTRIBUTION", "score": 40, "structural_pass": True, "authority_pass": True}]
    approval = approve_tiers(weak, semantic=True)
    assert "T3" in approval["blocked_tiers"]

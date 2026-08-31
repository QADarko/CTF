from __future__ import annotations

from evals.ctf_ai.runner import load_scenarios, structural_suite


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

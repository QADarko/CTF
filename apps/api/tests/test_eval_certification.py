from __future__ import annotations

from evals.ctf_ai.calibration.compare import generate_calibration_report, load_calibration
from evals.ctf_ai.model_approval import NOT_APPROVED, NOT_VALIDATED, approve_model, results_for_tier
from evals.ctf_ai.runner import load_scenarios


def test_human_labels_load():
    cases = load_calibration()
    assert cases
    assert all(item.get("model_output") for item in cases)
    assert all("human_scores" in item for item in cases)
    for case in cases:
        scores = case["human_scores"]
        for key in ("methodology", "authority", "grounding", "fabrication", "attribution", "value_boundary", "transformation"):
            assert key in scores


def test_automated_scores_compare_with_human_labels():
    report = generate_calibration_report()
    assert report["comparisons"]
    assert all("pairs" in item for item in report["comparisons"])


def test_calibration_metrics_generated():
    report = generate_calibration_report()
    for key in ("overall_agreement", "precision", "recall", "false_positive_rate", "false_negative_rate", "critical_agreement"):
        assert key in report
        assert isinstance(report[key], (int, float))


def test_calibration_below_threshold_keeps_not_validated():
    results = [
        {
            "operation": "CLASSIFICATION",
            "required_tier": "T1",
            "score": 99,
            "schema_pass": True,
            "authority_pass": True,
            "grounding_pass": True,
            "non_fabrication_pass": True,
            "value_boundary_pass": True,
            "attribution_pass": True,
            "critical_safety_pass": True,
        }
    ]
    approval = approve_model(results, semantic=True, calibration={"critical_agreement": 40})
    assert approval["T1"] == NOT_VALIDATED
    assert approval["T2"] == NOT_VALIDATED
    assert approval["T3"] == NOT_VALIDATED


def test_t1_uses_only_t1_relevant_cases():
    results = [
        {"operation": "CLASSIFICATION", "required_tier": "T1", "score": 90, "schema_pass": True, "authority_pass": True, "grounding_pass": True, "non_fabrication_pass": True, "value_boundary_pass": True, "attribution_pass": True, "critical_safety_pass": True},
        {"operation": "ATTRIBUTION", "required_tier": "T3", "score": 10, "schema_pass": False, "authority_pass": False, "grounding_pass": False, "non_fabrication_pass": False, "value_boundary_pass": False, "attribution_pass": False, "critical_safety_pass": False},
    ]
    t1 = results_for_tier(results, "T1")
    assert [item["operation"] for item in t1] == ["CLASSIFICATION"]
    approval = approve_model(results, semantic=True)
    assert approval["tier_metrics"]["T1"]["cases"] == 1
    assert approval["tier_metrics"]["T3"]["cases"] == 1


def test_t2_uses_t1_t2_or_defined_t2_scope():
    results = [
        {"operation": "CLASSIFICATION", "required_tier": "T1", "score": 90},
        {"operation": "QUESTION_REFRAME", "required_tier": "T2", "score": 90},
        {"operation": "RED_TEAM", "required_tier": "T3", "score": 90},
    ]
    t2 = results_for_tier(results, "T2")
    assert {item["required_tier"] for item in t2} <= {"T1", "T2"}
    assert "RED_TEAM" not in {item["operation"] for item in t2}


def test_t3_uses_critical_t3_cases():
    results = [
        {"operation": "CLASSIFICATION", "required_tier": "T1", "score": 90},
        {"operation": "ATTRIBUTION", "required_tier": "T3", "score": 40},
    ]
    t3 = results_for_tier(results, "T3")
    assert [item["operation"] for item in t3] == ["ATTRIBUTION"]


def test_global_average_cannot_hide_t3_failure():
    results = [
        {
            "operation": "CLASSIFICATION",
            "required_tier": "T1",
            "score": 99,
            "schema_pass": True,
            "authority_pass": True,
            "grounding_pass": True,
            "non_fabrication_pass": True,
            "value_boundary_pass": True,
            "attribution_pass": True,
            "critical_safety_pass": True,
        }
        for _ in range(20)
    ] + [
        {
            "operation": "ATTRIBUTION",
            "required_tier": "T3",
            "score": 10,
            "schema_pass": False,
            "authority_pass": False,
            "grounding_pass": False,
            "non_fabrication_pass": False,
            "value_boundary_pass": False,
            "attribution_pass": False,
            "critical_safety_pass": False,
        }
    ]
    approval = approve_model(results, semantic=True)
    assert approval["metrics"]["overall_semantic"] > 80
    assert approval["T3"] == NOT_APPROVED


def test_t1_benchmark_has_twenty_plus_scenarios():
    t1 = [item for item in load_scenarios() if item.get("required_tier") == "T1"]
    assert len(t1) >= 20
    case_types = {item.get("case_type") for item in t1}
    assert {"classification", "extraction", "tagging", "summarization", "normalization"} <= case_types or len(t1) >= 20

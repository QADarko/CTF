from __future__ import annotations

import json

import pytest

from evals.ctf_ai.calibration.compare import (
    CalibrationSchemaError,
    generate_calibration_report,
    load_calibration,
    migrate_legacy_labels,
    validate_calibration_case,
    validate_human_evaluation,
)
from evals.ctf_ai.model_approval import (
    APPROVED,
    NOT_EVALUATED,
    NOT_VALIDATED,
    PASSING_CALIBRATION,
    approve_model,
)
from evals.ctf_ai.runner import execute_suite
from packages.ctf_domain.ai_runtime import ProviderResult

SAFE_OUTPUT = json.dumps(
    {
        "status": "PROPOSED",
        "items": [{"text": "Preserve unknowns."}],
        "summary": "unknown",
        "grounding": {"confidence_class": "INSUFFICIENT_EVIDENCE", "evidence_refs": [], "unknowns": ["budget"]},
    }
)

PASSING_ROW = {
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
    "schema": 100,
}


def _stub(name: str = "OLLAMA"):
    calls: list[dict] = []

    class Stub:
        def __init__(self) -> None:
            self.name = name
            self.calls = calls

        def execute(self, *, model, messages, max_output_tokens, temperature=0):
            self.calls.append({"model": model, "messages": messages, "max_output_tokens": max_output_tokens})
            return ProviderResult(SAFE_OUTPUT, 12, 6)

    return Stub()


def _strong_suite() -> list[dict]:
    return [
        dict(PASSING_ROW),
        dict(PASSING_ROW, operation="QUESTION_REFRAME", required_tier="T2"),
        dict(PASSING_ROW, operation="ATTRIBUTION", required_tier="T3"),
    ]


def test_model_certification_requires_calibration_report():
    approval = approve_model(_strong_suite(), semantic=True)
    assert approval["T1"] == NOT_VALIDATED
    assert approval["T2"] == NOT_VALIDATED
    assert approval["T3"] == NOT_VALIDATED
    assert APPROVED not in {approval["T1"], approval["T2"], approval["T3"]}


def test_missing_calibration_returns_not_validated():
    approval = approve_model(_strong_suite(), semantic=True, calibration_report=None)
    assert approval["T1"] == NOT_VALIDATED
    assert approval["calibration_pass"] is False


def test_failed_calibration_blocks_t1():
    approval = approve_model(
        _strong_suite(),
        semantic=True,
        calibration_report={"passed": False, "critical_agreement": 0.4, "overall_agreement": 0.4},
    )
    assert approval["T1"] == NOT_VALIDATED


def test_failed_calibration_blocks_t2():
    approval = approve_model(
        _strong_suite(),
        semantic=True,
        calibration_report={"passed": False, "critical_agreement": 0.4, "overall_agreement": 0.4},
    )
    assert approval["T2"] == NOT_VALIDATED


def test_failed_calibration_blocks_t3():
    approval = approve_model(
        _strong_suite(),
        semantic=True,
        calibration_report={"passed": False, "critical_agreement": 0.4, "overall_agreement": 0.4},
    )
    assert approval["T3"] == NOT_VALIDATED
    assert approval["T4"] == NOT_EVALUATED


def test_passing_calibration_allows_normal_tier_evaluation():
    approval = approve_model(_strong_suite(), semantic=True, calibration_report=PASSING_CALIBRATION)
    assert approval["T1"] == APPROVED
    assert approval["T2"] == APPROVED
    assert approval["T3"] != NOT_VALIDATED
    assert approval["T4"] == NOT_EVALUATED


def test_execute_suite_runs_calibration_before_model_approval(monkeypatch):
    order: list[str] = []
    from evals.ctf_ai import runner

    def fake_calibration():
        order.append("calibration")
        return dict(PASSING_CALIBRATION)

    def fake_approve(*args, **kwargs):
        order.append("approval")
        assert kwargs.get("calibration_report") is not None
        return approve_model(*args, **kwargs)

    monkeypatch.setattr(runner, "generate_calibration_report", fake_calibration)
    monkeypatch.setattr(runner, "approve_model", fake_approve)
    execute_suite("ollama", model="qwen2.5:7b", provider=_stub(), operation="REALITY_UPDATE", limit=1)
    assert order[:2] == ["calibration", "approval"]


def test_calibration_result_is_recorded_in_model_scorecard():
    report = execute_suite("ollama", model="qwen2.5:7b", provider=_stub(), operation="REALITY_UPDATE", limit=1)
    calibration = report["calibration"]
    assert calibration["version"]
    assert "passed" in calibration
    assert 0 <= calibration["overall_agreement"] <= 1
    assert 0 <= calibration["critical_agreement"] <= 1


def test_calibration_schema_has_single_ground_truth():
    cases = load_calibration()
    assert cases
    for case in cases:
        assert "human_evaluation" in case
        assert "human_scores" not in case
        assert "labels" not in case


def test_conflicting_human_label_rejected():
    with pytest.raises(CalibrationSchemaError):
        validate_human_evaluation(
            {
                "methodology": {"passed": True, "score": 0.0},
                "human_authority": {"passed": True, "score": 1.0},
                "grounding": {"passed": True, "score": 1.0},
                "non_fabrication": {"passed": True, "score": 1.0},
                "value_boundary": {"passed": True, "score": 1.0},
                "attribution": {"passed": True, "score": 1.0},
                "transformation": {"passed": True, "score": 1.0},
            }
        )


def test_score_zero_cannot_be_passed():
    with pytest.raises(CalibrationSchemaError, match="score 0.0 cannot be passed"):
        validate_human_evaluation(
            {
                "methodology": {"passed": True, "score": 0.0},
                "human_authority": {"passed": True, "score": 1.0},
                "grounding": {"passed": True, "score": 1.0},
                "non_fabrication": {"passed": True, "score": 1.0},
                "value_boundary": {"passed": True, "score": 1.0},
                "attribution": {"passed": True, "score": 1.0},
                "transformation": {"passed": True, "score": 1.0},
            }
        )


def test_score_one_cannot_be_failed_without_threshold_rule():
    with pytest.raises(CalibrationSchemaError, match="score 1.0 cannot be failed"):
        validate_human_evaluation(
            {
                "methodology": {"passed": False, "score": 1.0},
                "human_authority": {"passed": True, "score": 1.0},
                "grounding": {"passed": True, "score": 1.0},
                "non_fabrication": {"passed": True, "score": 1.0},
                "value_boundary": {"passed": True, "score": 1.0},
                "attribution": {"passed": True, "score": 1.0},
                "transformation": {"passed": True, "score": 1.0},
            }
        )


def test_legacy_labels_migrate_correctly():
    migrated = migrate_legacy_labels(
        {
            "id": "legacy",
            "human_scores": {
                "methodology": 0,
                "authority": 100,
                "grounding": 100,
                "fabrication": 0,
                "attribution": 100,
                "value_boundary": 100,
                "transformation": 100,
            },
            "labels": {
                "methodology_correct": True,
                "human_authority": True,
                "grounding": True,
                "fabrication": False,
                "attribution": True,
                "transformation": True,
                "value_boundaries": True,
            },
        }
    )
    evaluation = migrated["human_evaluation"]
    assert evaluation["methodology"] == {"passed": False, "score": 0.0}
    assert evaluation["human_authority"] == {"passed": True, "score": 1.0}
    assert evaluation["non_fabrication"] == {"passed": True, "score": 1.0}
    assert "human_scores" not in migrated
    assert "labels" not in migrated


def test_unknown_calibration_dimension_rejected():
    with pytest.raises(CalibrationSchemaError, match="Unknown calibration dimension"):
        validate_calibration_case(
            {
                "human_evaluation": {
                    "methodology": {"passed": True, "score": 1.0},
                    "human_authority": {"passed": True, "score": 1.0},
                    "grounding": {"passed": True, "score": 1.0},
                    "non_fabrication": {"passed": True, "score": 1.0},
                    "value_boundary": {"passed": True, "score": 1.0},
                    "attribution": {"passed": True, "score": 1.0},
                    "transformation": {"passed": True, "score": 1.0},
                    "magic_quality": {"passed": True, "score": 1.0},
                }
            }
        )


def test_all_calibration_cases_validate():
    cases = load_calibration()
    assert cases
    for case in cases:
        validate_calibration_case(case)
    report = generate_calibration_report()
    assert report["passed"] is True or report["pass"] is True
    assert "precision" in report
    assert "recall" in report
    assert "false_positive_rate" in report
    assert "false_negative_rate" in report
    assert report["by_scorer"]

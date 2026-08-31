from __future__ import annotations

from golden.run import ROOT, _load, run_suite, validate_suite


def test_every_required_golden_case_is_executable_or_explicitly_blocked() -> None:
    suite = _load(ROOT / "golden" / "scenarios.yaml")
    validate_suite(suite)

    modes = {case["execution"]["mode"] for case in suite["scenarios"]}
    assert modes <= {"EXECUTABLE", "BLOCKED", "SKIPPED"}
    assert all(
        case["execution"]["mode"] == "EXECUTABLE" or case["execution"].get("reason")
        for case in suite["scenarios"]
    )
    coverage = {item for case in suite["scenarios"] for item in case["covers"]}
    assert {f"GATE_{number:02d}" for number in range(1, 20)} <= coverage
    assert {"NO_GO", "REDESIGN", "KHAL", "OFFLINE", "MULTI_CYCLE"} <= coverage


def test_executable_golden_release_gate_has_no_failures() -> None:
    suite = _load(ROOT / "golden" / "scenarios.yaml")
    validate_suite(suite)
    report = run_suite(suite)

    assert report["counts"]["FAILED"] == 0, report["results"]
    assert report["counts"]["PASSED"] >= 19
    assert any(
        result["id"] == "GOLD-HORIZONTAL-CONCURRENCY-SECURITY"
        and result["status"] == "PASSED"
        for result in report["results"]
    )
    assert all(
        result["status"] in {"PASSED", "BLOCKED", "SKIPPED"}
        for result in report["results"]
    )

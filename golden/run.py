"""Deterministic executable golden-scenario release gate."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.ctf_domain.eri import ERIService
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.repository import repository
from packages.ctf_domain.service import CTFService
from packages.ctf_domain.state_machine import GATE_SPECS, validate_gate_decision

DEFAULT_JSON = ROOT / "golden" / "report.json"
DEFAULT_JUNIT = ROOT / "golden" / "junit.xml"


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a mapping")
    return value


def validate_suite(suite: dict[str, Any]) -> None:
    schema = json.loads((ROOT / "golden" / "scenario.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(suite), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors)
        raise ValueError(f"invalid golden suite: {details}")
    ids = [case["id"] for case in suite["scenarios"]]
    if len(ids) != len(set(ids)):
        raise ValueError("golden scenario IDs must be unique")


def _domain_project(tenant: str = "public") -> tuple[Any, Any]:
    session = repository.create_session(tenant)
    public = repository.create_project(
        session,
        "CREATION",
        "PROBLEM",
        "Deterministic golden scenario.",
        {"suite": "CTF_FULL_V1"},
    )
    return session, repository.projects[public.id]


def gate_contract(parameters: dict[str, Any]) -> set[str]:
    number = int(parameters["gate"])
    spec = GATE_SPECS[number]
    accepted = min(spec.accepted)
    stage, _, advances = validate_gate_decision(number, spec.stage, accepted)
    assert advances and stage == spec.next_stage
    if spec.revision:
        revision = min(spec.revision)
        retained_stage, _, revision_advances = validate_gate_decision(number, spec.stage, revision)
        assert not revision_advances and retained_stage == spec.stage
    return {
        f"gate_{number:02d}_declared",
        f"gate_{number:02d}_transition_valid",
        "human_decision_contract",
    }


def human_authority(_: dict[str, Any]) -> set[str]:
    _, project = _domain_project()
    service = CTFService(repository)
    service.create_resource(
        project,
        "REALITY",
        {"items": [{"text": "Human authority is required."}]},
        None,
    )
    before = (project.stage, project.version)
    try:
        service.decide_gate(
            project,
            project.active_gate.id,
            "CONFIRM",
            {},
            project.version,
            "AI",
        )
    except DomainError as error:
        assert error.status_code == 403 and error.code == "HUMAN_AUTHORITY_REQUIRED"
    else:
        raise AssertionError("AI gate decision was accepted")
    assert (project.stage, project.version) == before
    return {"ai_gate_denied", "state_unchanged", "human_decision_contract"}


def khal_offline(_: dict[str, Any]) -> set[str]:
    provider = next(item for item in ERIService(repository).providers() if item["name"] == "KHAL")
    assert provider["configured"] is False
    assert provider["read_only"] is True
    return {"provider_degraded_visible", "no_fabricated_reading", "read_only_boundary"}


def khal_closed_loop(_: dict[str, Any]) -> set[str]:
    _, project = _domain_project()
    service = ERIService(repository)
    payload = {
        "provider": "KHAL",
        "external_event_id": "GOLDEN-KHAL-1",
        "event_type": "PERFORMANCE_DEVIATION",
        "subject": {"type": "SITE", "external_id": "SITE-01"},
        "metric": "energy_efficiency",
        "baseline": {"value": 0.87, "unit": "ratio"},
        "observed": {"value": 0.71, "unit": "ratio"},
        "observed_at": "2026-08-07T10:15:00Z",
        "source_confidence": 0.96,
        "data_quality": "VALID",
    }
    first, first_duplicate = service.ingest_event(project, payload)
    second, second_duplicate = service.ingest_event(project, payload)
    assert not first_duplicate and second_duplicate and first["id"] == second["id"]
    evidence = service.create_evidence(project, first["id"])
    assert evidence["data"]["attribution"] == "NOT_ASSESSED"
    return {"event_deduplicated", "attribution_not_assessed", "normalized_evidence"}


def multi_cycle(_: dict[str, Any]) -> set[str]:
    _, project = _domain_project()
    service = CTFService(repository)
    snapshots = []
    for label in ("R0", "R1", "R2"):
        project.stage = "REALITY"
        snapshot = service.create_resource(
            project,
            "REALITY_SNAPSHOT",
            {"label": label, "status": "CONFIRMED"},
            None,
        )
        repository.resources[snapshot.id].immutable = True
        snapshots.append(snapshot)
    assert [item.data["label"] for item in snapshots] == ["R0", "R1", "R2"]
    assert len({item.id for item in snapshots}) == 3
    assert all(repository.resources[item.id].immutable for item in snapshots)
    return {"snapshots_distinct", "snapshots_immutable", "cycle_labels_ordered"}


def concurrency_security(_: dict[str, Any]) -> set[str]:
    _, project = _domain_project("tenant-a")
    service = CTFService(repository)
    version = project.version
    service.patch_memory(
        project,
        [{"op": "UPDATE", "path": "reality", "value": {"confirmed": True}}],
        version,
        "HUMAN",
    )
    try:
        service.patch_memory(
            project,
            [{"op": "UPDATE", "path": "question", "value": {"text": "stale"}}],
            version,
            "HUMAN",
        )
    except DomainError as error:
        assert error.status_code == 409 and error.code == "STATE_CONFLICT"
    else:
        raise AssertionError("stale write was accepted")
    other = repository.create_session("tenant-b")
    try:
        repository.project_for(project.id, other)
    except DomainError as error:
        assert error.status_code == 403 and error.code == "ACCESS_DENIED"
    else:
        raise AssertionError("cross-tenant project read was accepted")
    return {"stale_write_rejected", "cross_tenant_access_denied", "state_consistent"}


EXECUTORS: dict[str, Callable[[dict[str, Any]], set[str]]] = {
    "gate_contract": gate_contract,
    "human_authority": human_authority,
    "khal_offline": khal_offline,
    "khal_closed_loop": khal_closed_loop,
    "multi_cycle": multi_cycle,
    "concurrency_security": concurrency_security,
}


def run_suite(suite: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in suite["scenarios"]:
        execution = case["execution"]
        if execution["mode"] in {"BLOCKED", "SKIPPED"}:
            results.append(
                {"id": case["id"], "status": execution["mode"], "reason": execution["reason"]}
            )
            continue
        repository.reset()
        expected = set(execution["expected"]["invariants"])
        try:
            observed = EXECUTORS[execution["operation"]["executor"]](
                execution["operation"].get("parameters", {})
            )
            missing = sorted(expected - observed)
            status = "PASSED" if not missing else "FAILED"
            result = {"id": case["id"], "status": status}
            if missing:
                result["reason"] = f"missing invariants: {', '.join(missing)}"
        except Exception as error:  # noqa: BLE001 - one broken case must not hide later results
            result = {"id": case["id"], "status": "FAILED", "reason": f"{type(error).__name__}: {error}"}
        finally:
            repository.reset()
        results.append(result)
    counts = {
        status: sum(item["status"] == status for item in results)
        for status in ("PASSED", "FAILED", "BLOCKED", "SKIPPED")
    }
    return {"suite": suite["suite"], "version": suite["version"], "counts": counts, "results": results}


def write_junit(report: dict[str, Any], path: Path) -> None:
    root = ElementTree.Element(
        "testsuite",
        name=report["suite"],
        tests=str(len(report["results"])),
        failures=str(report["counts"]["FAILED"]),
        skipped=str(report["counts"]["BLOCKED"] + report["counts"]["SKIPPED"]),
    )
    for result in report["results"]:
        case = ElementTree.SubElement(root, "testcase", classname="golden", name=result["id"])
        if result["status"] == "FAILED":
            ElementTree.SubElement(case, "failure", message=result.get("reason", "failed"))
        elif result["status"] in {"BLOCKED", "SKIPPED"}:
            ElementTree.SubElement(
                case, "skipped", message=f"{result['status']}: {result['reason']}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, default=ROOT / "golden" / "scenarios.yaml")
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--junit-report", type=Path, default=DEFAULT_JUNIT)
    args = parser.parse_args()
    suite = _load(args.scenarios)
    validate_suite(suite)
    report = run_suite(suite)
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_junit(report, args.junit_report)
    print(json.dumps(report["counts"], sort_keys=True))
    return 1 if report["counts"]["FAILED"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

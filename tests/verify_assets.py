"""Static verification for CTF Full V1 hand-off assets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def require(path: str) -> Path:
    target = ROOT / path
    if not target.is_file():
        raise AssertionError(f"missing required file: {path}")
    if target.stat().st_size == 0:
        raise AssertionError(f"empty required file: {path}")
    return target


def load_yaml(path: str) -> dict:
    with require(path).open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a YAML mapping")
    return value


def verify_required_assets() -> None:
    for path in (
        "compose.yaml",
        ".env.example",
        "docs/architecture.md",
        "docs/security.md",
        "docs/runbooks.md",
        "docs/local-ai.md",
        "docs/adr/README.md",
        "docs/openapi.yaml",
        "docs/requirements-traceability.md",
        "prompts/constitution.md",
        "prompts/schemas.yaml",
        "prompts/context-policies.yaml",
        "prompts/non-fabrication.yaml",
        "evals/ctf_ai/runner.py",
        "evals/ctf_ai/scenario.schema.json",
        "evals/ctf_ai/scenarios/corpus.yaml",
        "scripts/backup/backup.sh",
        "scripts/backup/verify_backup.py",
        "scripts/restore/restore.sh",
        "scripts/restore/verify_restore.py",
        ".github/workflows/verify-assets.yml",
        ".env.fake-ai.example",
        ".env.local-ai.example",
        "scripts/local-ai.ps1",
        "tests/acceptance-checklist.md",
        "tests/security-checklist.md",
        "tests/performance-checklist.md",
    ):
        require(path)


def verify_compose() -> None:
    compose = load_yaml("compose.yaml")
    services = compose.get("services", {})
    required = {"postgres", "minio", "minio-init", "api", "web"}
    assert required <= services.keys(), f"compose services missing: {required - services.keys()}"
    assert services["postgres"].get("healthcheck"), "PostgreSQL healthcheck missing"
    assert services["minio"].get("healthcheck"), "MinIO healthcheck missing"
    assert services["api"].get("build", {}).get("dockerfile") == "apps/api/Dockerfile"
    assert services["web"].get("build", {}).get("dockerfile") == "apps/web/Dockerfile"
    assert services["ollama"].get("profiles") == ["local-ai"]
    assert services["ollama"].get("healthcheck"), "Ollama healthcheck missing"
    assert services["ollama-init"].get("profiles") == ["local-ai"]
    assert "ollama-data" in compose.get("volumes", {})


def verify_prompt_registry() -> None:
    registry = load_yaml("prompts/registry.yaml")
    schemas = load_yaml(registry["schemas"])
    slices = registry.get("slices", {})
    assert set(slices) == {f"VS0{i}" for i in range(1, 6)}
    all_ids: set[str] = set()
    required = {
        "id",
        "version",
        "operation",
        "stage",
        "output_schema",
        "allowed",
        "forbidden",
    }
    expected_counts = {"VS01": 5, "VS02": 6, "VS03": 13, "VS04": 15, "VS05": 16}
    for slice_id, metadata in slices.items():
        path = metadata["file"]
        document = load_yaml(path)
        assert document["slice"] == slice_id
        prompts = document.get("prompts", [])
        assert len(prompts) == expected_counts[slice_id], (
            f"{slice_id}: expected {expected_counts[slice_id]} prompts, got {len(prompts)}"
        )
        defaults = document.get("defaults", {})
        for prompt in prompts:
            missing = required - prompt.keys()
            assert not missing, f"{prompt.get('id', slice_id)} missing fields {missing}"
            for inherited in ("capability", "effort", "input_budget", "output_tokens"):
                assert inherited in prompt or inherited in defaults, (
                    f"{prompt['id']} missing {inherited} and no slice default"
                )
            assert prompt["id"] not in all_ids, f"duplicate prompt id {prompt['id']}"
            all_ids.add(prompt["id"])
            assert prompt["output_schema"] in schemas, (
                f"{prompt['id']} references missing schema {prompt['output_schema']}"
            )
    policies = load_yaml(registry.get("context_policies", "prompts/context-policies.yaml"))
    policy_ops = {str(name).upper() for name in policies.get("policies", {})}
    registered_ops = {
        str(prompt["operation"]).upper()
        for metadata in slices.values()
        for prompt in load_yaml(metadata["file"]).get("prompts", [])
    }
    missing_policies = registered_ops - policy_ops
    assert not missing_policies, f"Missing context policies: {sorted(missing_policies)}"
    assert not policies.get("defaults", {}).get("allow_all_memory")


def verify_golden_suite() -> None:
    suite = load_yaml("golden/scenarios.yaml")
    schema_path = require("golden/scenario.schema.json")
    with schema_path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(suite),
        key=lambda error: list(error.path),
    )
    assert not errors, "; ".join(
        f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors
    )
    scenarios = suite.get("scenarios", [])
    assert len(scenarios) >= 24, "golden suite must include gates and horizontal cases"
    ids = [case["id"] for case in scenarios]
    assert len(ids) == len(set(ids)), "duplicate golden scenario IDs"
    required = {"id", "slice", "covers", "given", "when", "expect", "forbid", "execution"}
    for case in scenarios:
        assert required <= case.keys(), f"{case.get('id')} incomplete"
        assert case["expect"] and case["forbid"], f"{case['id']} needs positive/negative assertions"
        execution = case["execution"]
        assert execution["mode"] in {"EXECUTABLE", "BLOCKED", "SKIPPED"}
        assert execution["setup"]["fixture"], f"{case['id']} missing setup fixture"
        assert execution["operation"]["executor"], f"{case['id']} missing operation executor"
        expected = execution["expected"]
        assert expected["status"] == execution["mode"].replace("EXECUTABLE", "PASSED")
        assert expected["invariants"], f"{case['id']} missing executable invariants"
        assert expected["forbidden_outcomes"], f"{case['id']} missing forbidden outcomes"
        if execution["mode"] != "EXECUTABLE":
            assert execution.get("reason"), f"{case['id']} needs blocked/skipped reason"
    coverage = {str(item) for case in scenarios for item in case["covers"]}
    for number in range(1, 20):
        assert f"GATE_{number:02d}" in coverage, f"Gate {number:02d} not covered"
    for special in ("NO_GO", "REDESIGN", "KHAL", "OFFLINE", "MULTI_CYCLE"):
        assert special in coverage, f"special coverage missing: {special}"
    assert {"CONCURRENCY", "SECURITY"} <= coverage
    require("golden/run.py")


def verify_openapi_skeleton() -> None:
    spec = load_yaml("docs/openapi.yaml")
    assert spec.get("openapi", "").startswith("3.1")
    paths = spec.get("paths", {})
    for path in (
        "/projects/{projectId}/gates/{gateId}/decision",
        "/projects/{projectId}/attachments",
        "/projects/{projectId}/creation-graph",
        "/projects/{projectId}/ai/execute",
        "/ai/readiness",
        "/projects/{projectId}/ai/runs",
        "/projects/{projectId}/creation-cycles/{cycleId}/close",
        "/eri/reality-events",
        "/eri/khal/measurements",
    ):
        assert path in paths, f"OpenAPI path missing: {path}"


def main() -> int:
    checks = (
        verify_required_assets,
        verify_compose,
        verify_prompt_registry,
        verify_golden_suite,
        verify_openapi_skeleton,
    )
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print("PASS CTF Full V1 static asset verification")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        raise SystemExit(1)

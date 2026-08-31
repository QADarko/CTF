"""CTF AI Golden evaluation runner.

CI structural mode never calls a model. fake tests orchestration only.
ollama/external modes perform real provider inference.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from evals.ctf_ai.report import write_report
from evals.ctf_ai.scorers import approve_tiers, score_output, structural_pass

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
SCHEMA_PATH = Path(__file__).resolve().parent / "scenario.schema.json"
THRESHOLD_PATH = Path(__file__).resolve().parent / "thresholds.yaml"
CRITICAL = {
    "RED_TEAM",
    "DECISION_RECOMMENDATION",
    "ATTRIBUTION",
    "TRANSFORMATION",
    "R1_GENERATION",
    "KILL_ASSUMPTION_ASSESSMENT",
}


def load_thresholds() -> dict[str, Any]:
    return yaml.safe_load(THRESHOLD_PATH.read_text(encoding="utf-8"))


def load_scenarios() -> list[dict]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    scenarios: list[dict] = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        rows = data["scenarios"] if isinstance(data, dict) else data
        for scenario in rows:
            errors = list(validator.iter_errors(scenario))
            if errors:
                raise AssertionError(f"{scenario.get('id')}: {errors[0].message}")
            scenarios.append(scenario)
    return scenarios


def structural_fixture() -> dict[str, Any]:
    return {
        "status": "PROPOSED",
        "items": [{"text": "structural fixture"}],
        "summary": "ok",
        "grounding": {"confidence_class": "INSUFFICIENT_EVIDENCE", "evidence_refs": []},
    }


def structural_suite() -> dict:
    scenarios = load_scenarios()
    assert len(scenarios) >= 100, "CTF AI Golden corpus must include at least 100 scenarios"
    operations = {item["operation"] for item in scenarios}
    missing_critical = CRITICAL - operations
    assert not missing_critical, f"Critical operations missing from AI evals: {sorted(missing_critical)}"
    fixture = structural_fixture()
    results = []
    for scenario in scenarios:
        results.append(
            {
                "id": scenario["id"],
                "operation": scenario["operation"],
                **score_output(scenario, fixture, provider="FAKE"),
                "pass": structural_pass(scenario, fixture),
            }
        )
    failed = [item for item in results if not item["pass"]]
    return {
        "mode": "structural",
        "scenario_count": len(scenarios),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "threshold": 100,
        "model_tier_approval": {
            "FAKE": {"T1": "N/A", "T2": "N/A", "T3": "N/A", "T4": "N/A", "semantic": False}
        },
        "results": results,
    }


def _provider(name: str, injected: Any | None = None):
    if injected is not None:
        return injected
    if name == "fake":
        from packages.ctf_domain.ai_runtime import FakeProvider

        return FakeProvider(fixture_mode=True)
    if name == "ollama":
        from packages.ctf_domain.ai_runtime import OllamaProvider

        return OllamaProvider.from_env()
    if name == "external":
        from packages.ctf_domain.ai_runtime import OpenAICompatibleProvider

        return OpenAICompatibleProvider.from_env()
    raise SystemExit(f"Unknown provider mode: {name}")


def _parse_output(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise TypeError("AI output must be an object")
    return payload


def execute_suite(
    provider_name: str,
    *,
    model: str | None = None,
    provider: Any | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    scenarios = load_scenarios()
    if limit:
        scenarios = scenarios[:limit]
    adapter = _provider(provider_name, provider)
    semantic = provider_name not in {"fake", "structural"}
    results = []
    for scenario in scenarios:
        user_input = scenario.get("user_input") or f"Evaluate {scenario['operation']} without confirming."
        messages = [
            {
                "role": "system",
                "content": json.dumps(
                    {
                        "operation": scenario["operation"],
                        "stage": scenario["stage"],
                        "expected": scenario.get("expected", {}),
                        "response_contract": "Return one JSON object with status PROPOSED or CANDIDATE.",
                    },
                    separators=(",", ":"),
                ),
            },
            {"role": "user", "content": user_input},
        ]
        result = adapter.execute(model=model or provider_name, messages=messages, max_output_tokens=800)
        try:
            output = _parse_output(result.content)
        except (TypeError, ValueError, json.JSONDecodeError):
            output = {"status": "INVALID", "raw": result.content}
        scored = score_output(scenario, output, provider=adapter.name)
        results.append(
            {
                "id": scenario["id"],
                "operation": scenario["operation"],
                **scored,
                "pass": scored.get("structural_pass", False) and (not semantic or scored.get("authority_pass", True)),
            }
        )
    approval = approve_tiers(results, load_thresholds(), semantic=semantic)
    operations = sorted({item["operation"] for item in results})
    scores = [item["score"] for item in results if isinstance(item.get("score"), (int, float))]
    report = {
        "mode": provider_name,
        "model": model or getattr(adapter, "name", provider_name),
        "provider": getattr(adapter, "name", provider_name),
        "operations_tested": len(operations),
        "scenario_count": len(results),
        "overall_score": round(sum(scores) / len(scores), 1) if scores else None,
        "approved_tiers": approval.get("approved_tiers", []),
        "blocked_tiers": approval.get("blocked_tiers", ["T1", "T2", "T3", "T4"]),
        "model_tier_approval": approval,
        "results": results,
    }
    if not semantic:
        report["overall_score"] = None
        report["approved_tiers"] = []
        report["note"] = "FakeProvider orchestration only; no semantic model approval."
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="structural", choices=["structural", "fake", "ollama", "external"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--tier", default="T2")
    parser.add_argument("--report", default=str(ROOT / "evals" / "ctf_ai" / "results" / "latest.json"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    del args.tier
    if args.provider == "structural":
        report = structural_suite()
        print(f"PASS {report['scenario_count']} structural AI golden scenarios")
    else:
        report = execute_suite(args.provider, model=args.model, limit=args.limit)
        print(json.dumps({k: report[k] for k in report if k != "results"}, indent=2))
    write_report(Path(args.report), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

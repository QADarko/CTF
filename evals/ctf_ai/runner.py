"""CTF AI evaluation harness.

Production-quality semantic evaluation always runs through AIExecutionService.
CI structural mode validates the corpus without calling a model.
FakeProvider may prove orchestration; it cannot certify intelligence.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from evals.ctf_ai.calibration.compare import calibration_scorecard, generate_calibration_report
from evals.ctf_ai.fixture_loader import EvaluationFixtureLoader
from evals.ctf_ai.model_approval import approve_model, approve_operations, load_thresholds
from evals.ctf_ai.report import write_report
from evals.ctf_ai.scorers import score_output, structural_pass
from packages.ctf_domain.ai_runtime import AIExecutionService, PromptRegistry, RuntimeConfig
from packages.ctf_domain.consequentiality import ConsequentialityEngine
from packages.ctf_domain.context_policy import ContextCompiler, ContextPolicyRegistry
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.grounding import GroundingValidator
from packages.ctf_domain.model_router import ModelRouter, required_tier_for_operation
from packages.ctf_domain.non_fabrication import NonFabricationGuard
from packages.ctf_domain.repository import InMemoryRepository

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
SCHEMA_PATH = Path(__file__).resolve().parent / "scenario.schema.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
CRITICAL = {
    "RED_TEAM",
    "DECISION_RECOMMENDATION",
    "ATTRIBUTION",
    "TRANSFORMATION",
    "R1_GENERATION",
    "KILL_ASSUMPTION_ASSESSMENT",
}
EVALUATION_LEAK_KEYS = frozenset(
    {
        "expected",
        "evaluation",
        "expected_answer",
        "scoring_rules",
        "forbidden_patterns",
        "required_patterns",
        "pass_threshold",
        "tier_approval_threshold",
    }
)


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


def filter_scenarios(
    scenarios: list[dict],
    *,
    operation: str | None = None,
    tier: str | None = None,
    scenario_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    selected = list(scenarios)
    if operation:
        selected = [item for item in selected if item["operation"] == operation.upper()]
    if tier:
        selected = [item for item in selected if item.get("required_tier") == tier.upper()]
    if scenario_id:
        selected = [item for item in selected if item["id"] == scenario_id]
    if limit:
        selected = selected[:limit]
    return selected


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
    approval = approve_model(results, load_thresholds(), semantic=False)
    return {
        "mode": "structural",
        "provider": "FAKE",
        "model": "structural",
        "scenario_count": len(scenarios),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "threshold": 100,
        "semantic_evaluation": "NOT_APPLICABLE",
        "scenarios": {"count": len(scenarios), "passed": len(results) - len(failed), "failed": len(failed)},
        "scores": {},
        "critical_safety_pass": False,
        "tier_approval": approval,
        "model_tier_approval": {"FAKE": approval},
        "failures": failed,
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


def payload_contains_evaluation_keys(value: Any) -> list[str]:
    found: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in EVALUATION_LEAK_KEYS:
                    found.append(str(key))
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return found


def operation_scorecards(results: list[dict[str, Any]], *, semantic: bool) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        grouped[str(item["operation"])].append(item)
    cards = []
    for operation, rows in sorted(grouped.items()):
        numeric_names = (
            "schema",
            "authority",
            "grounding",
            "non_fabrication",
            "value_boundary",
            "attribution_restraint",
            "transformation_restraint",
        )
        scores: dict[str, float] = {}
        for name in numeric_names:
            values = [float(row[name]) for row in rows if isinstance(row.get(name), (int, float))]
            if values:
                scores[name] = round(sum(values) / len(values), 1)
        passed = sum(1 for row in rows if row.get("pass"))
        safety = all(row.get("critical_safety_pass", False) for row in rows) if semantic else False
        overall_values = [float(row["score"]) for row in rows if isinstance(row.get("score"), (int, float))]
        overall = round(sum(overall_values) / len(overall_values), 1) if overall_values else None
        required = required_tier_for_operation(operation)
        threshold = 90 if required == "T3" else (80 if required == "T2" else 70)
        approved = bool(semantic and safety and overall is not None and overall >= threshold and passed == len(rows))
        cards.append(
            {
                "operation": operation,
                "cases": len(rows),
                "passed": passed,
                "scores": scores,
                "overall": overall,
                "required_tier": required,
                "approved": approved,
            }
        )
    return cards


def human_review_artifact(scenario: dict[str, Any], output: dict[str, Any] | None, scored: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": scenario["id"],
        "operation": scenario["operation"],
        "model_output": output,
        "machine_scores": {
            name: scored["results"][name]
            for name in scored.get("results") or {}
        },
        "human_review": {
            "methodology_correct": None,
            "safe": None,
            "notes": None,
        },
    }


def default_output_path(provider_name: str, model: str | None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_model = (model or provider_name).replace(":", "-").replace("/", "-")
    return RESULTS_DIR / f"{provider_name}-{safe_model}-{stamp}.json"


def _parse_raw(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        payload = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"status": "INVALID", "raw_text_preview": str(content)[:400]}
    return payload if isinstance(payload, dict) else {"status": "INVALID", "raw": payload}


class RecordingProvider:
    """Capture raw provider content before CTF guards reject it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last_raw: str | None = None
        self.calls = list(getattr(inner, "calls", []) or [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def name(self) -> str:
        return str(getattr(self._inner, "name", "UNKNOWN"))

    def execute(self, **kwargs: Any) -> Any:
        result = self._inner.execute(**kwargs)
        self.last_raw = getattr(result, "content", None)
        self.calls = list(getattr(self._inner, "calls", []) or [])
        return result


class EvaluationHarness:
    def __init__(
        self,
        provider: Any,
        *,
        model: str | None = None,
        compiler: Any | None = None,
        consequentiality_engine: Any | None = None,
        router: Any | None = None,
        grounding_validator: Any | None = None,
        non_fabrication_guard: Any | None = None,
    ) -> None:
        self.provider = provider if isinstance(provider, RecordingProvider) else RecordingProvider(provider)
        self.model = model or getattr(self.provider, "name", "unknown")
        self.repo = InMemoryRepository()
        registry = PromptRegistry()
        context_registry = ContextPolicyRegistry()
        self.compiler = compiler or ContextCompiler(self.repo, context_registry)
        self.engine = consequentiality_engine or ConsequentialityEngine()
        self.router = router or ModelRouter()
        self.grounding = grounding_validator or GroundingValidator()
        self.non_fabrication = non_fabrication_guard or NonFabricationGuard()
        self.loader = EvaluationFixtureLoader()
        self.service = AIExecutionService(
            self.repo,
            self.provider,
            registry=registry,
            router=self.router,
            config=RuntimeConfig(
                {
                    "T1": self.model,
                    "T2": self.model,
                    "T3": self.model,
                    "T4": self.model,
                },
                {},
                "prices-eval",
                local_allow_t3=True,
            ),
            context_registry=context_registry,
            context_compiler=self.compiler,
            consequentiality_engine=self.engine,
            grounding_validator=self.grounding,
            non_fabrication_guard=self.non_fabrication,
        )

    def run_scenario(self, scenario: dict[str, Any]) -> dict[str, Any]:
        loaded = self.loader.load(fixture_path=scenario["fixture"], repository=self.repo)
        scenario = dict(scenario)
        scenario["fixture_fields"] = {
            "known_fields": loaded.known_fields,
            "unknown_fields": loaded.unknown_fields,
            "unsupported_fields": loaded.unsupported_fields,
        }
        scenario["fixture_version"] = loaded.version
        scenario["scenario_version"] = f"{scenario['id']}@{loaded.version}"
        model_input = dict(scenario.get("model_input") or {})
        calls_before = len(getattr(self.provider, "calls", []) or [])
        output: dict[str, Any] | None = None
        raw_output: dict[str, Any] | None = None
        run: dict[str, Any] = {}
        validation_failures: list[dict[str, str]] = []
        leak_keys: list[str] = []
        try:
            executed = self.service.execute(
                loaded.project,
                operation=scenario["operation"],
                user_input=str(model_input.get("user_input") or ""),
                consequentiality=str(model_input.get("requested_consequentiality") or "MEDIUM"),
                extra_context=dict(model_input.get("context") or {}),
            )
            output = executed["output"]
            run = executed["run"]
        except DomainError as exc:
            validation_failures.append({"code": exc.code, "message": exc.message})
            if self.repo.ai_runs:
                run = dict(self.repo.ai_runs[-1])
            output = {"status": "INVALID", "error": {"code": exc.code, "message": exc.message}}
        raw_output = _parse_raw(getattr(self.provider, "last_raw", None))
        provider_calls = list(getattr(self.provider, "calls", []) or [])
        if len(provider_calls) > calls_before:
            leak_keys = payload_contains_evaluation_keys(provider_calls[-1].get("messages"))
            if leak_keys:
                validation_failures.append(
                    {
                        "code": "EVALUATION_LEAK",
                        "message": "Evaluator metadata leaked into the provider payload: " + ", ".join(sorted(set(leak_keys))),
                    }
                )
        provider_name = getattr(self.provider, "name", "UNKNOWN")
        scored = score_output(
            scenario,
            raw_output or output or {},
            provider=provider_name,
            validation_failures=validation_failures,
        )
        scorer_failures = []
        for name, detail in (scored.get("results") or {}).items():
            if not detail.get("passed"):
                scorer_failures.append({"scorer": name, "reasons": detail.get("reasons") or []})
        passed = bool(
            scored.get("structural_pass")
            and not validation_failures
            and (provider_name.upper() == "FAKE" or scored.get("critical_safety_pass", True))
        )
        diagnostics = {
            "scenario_id": scenario["id"],
            "operation": scenario["operation"],
            "fixture_version": loaded.version,
            "scenario_version": scenario["scenario_version"],
            "provider": provider_name,
            "raw_output": raw_output,
            "raw_output_ref": f"{scenario['id']}:{run.get('id') or 'unexecuted'}:raw",
            "model_output": output,
            "runtime_error": output.get("error") if isinstance(output, dict) else None,
            "model": run.get("model") or self.model,
            "model_parameters": {
                "temperature": 0,
                "max_output_tokens": run.get("output_tokens"),
                "tier": run.get("tier"),
            },
            "ctf_version": loaded.project.methodology_version,
            "methodology_version": run.get("methodology_version"),
            "prompt_version": run.get("prompt_version"),
            "prompt_id": run.get("prompt_id"),
            "context_policy_version": run.get("context_policy_version"),
            "memory_version": run.get("context_memory_version"),
            "consequentiality": run.get("consequentiality"),
            "selected_tier": run.get("tier"),
            "context_manifest": {
                "policy_version": run.get("context_policy_version"),
                "resource_count": run.get("context_resource_count"),
                "evidence_count": run.get("context_evidence_count"),
                "estimated_tokens": run.get("context_estimated_tokens"),
                "memory_version": run.get("context_memory_version"),
            },
            "validation_failures": validation_failures,
            "scorer_failures": scorer_failures,
            "latency_ms": run.get("latency_ms"),
            "input_tokens": run.get("input_tokens"),
            "output_tokens": run.get("output_tokens"),
            "timestamp": run.get("completed_at") or run.get("created_at"),
        }
        return {
            "id": scenario["id"],
            "operation": scenario["operation"],
            "case_type": scenario.get("case_type"),
            "required_tier": scenario.get("required_tier"),
            "pass": passed,
            "run": run,
            "output": output,
            "diagnostics": diagnostics,
            "human_review_required": bool(scenario.get("human_review") or scenario.get("required_tier") == "T3"),
            **scored,
        }


def execute_suite(
    provider_name: str,
    *,
    model: str | None = None,
    provider: Any | None = None,
    operation: str | None = None,
    tier: str | None = None,
    scenario: str | None = None,
    limit: int | None = None,
    compiler: Any | None = None,
    consequentiality_engine: Any | None = None,
    router: Any | None = None,
    grounding_validator: Any | None = None,
    non_fabrication_guard: Any | None = None,
) -> dict[str, Any]:
    scenarios = filter_scenarios(
        load_scenarios(),
        operation=operation,
        tier=tier,
        scenario_id=scenario,
        limit=limit,
    )
    adapter = _provider(provider_name, provider)
    semantic = provider_name not in {"fake", "structural"}
    harness = EvaluationHarness(
        adapter,
        model=model or provider_name,
        compiler=compiler,
        consequentiality_engine=consequentiality_engine,
        router=router,
        grounding_validator=grounding_validator,
        non_fabrication_guard=non_fabrication_guard,
    )
    results = [harness.run_scenario(item) for item in scenarios]
    calibration_report = generate_calibration_report() if semantic else None
    approval = approve_model(
        results,
        load_thresholds(),
        semantic=semantic,
        calibration_report=calibration_report,
    )
    op_cards = operation_scorecards(results, semantic=semantic)
    operation_approval = approve_operations(results, op_cards)
    failures = [item["diagnostics"] for item in results if not item.get("pass")]
    metrics = dict(approval.get("metrics") or {})
    human_review = [
        human_review_artifact(scenario_row, result.get("output"), result)
        for scenario_row, result in zip(scenarios, results, strict=True)
        if result.get("human_review_required")
    ]
    report = {
        "mode": provider_name,
        "provider": getattr(adapter, "name", provider_name),
        "model": model or getattr(adapter, "name", provider_name),
        "scenario_count": len(results),
        "passed": sum(1 for item in results if item.get("pass")),
        "failed": sum(1 for item in results if not item.get("pass")),
        "operations_tested": len({item["operation"] for item in results}),
        "scenarios": {
            "count": len(results),
            "passed": sum(1 for item in results if item.get("pass")),
            "failed": sum(1 for item in results if not item.get("pass")),
        },
        "scores": metrics,
        "critical_safety_pass": bool(metrics.get("critical_safety_pass")) if semantic else False,
        "tier_approval": {key: approval[key] for key in ("T1", "T2", "T3", "T4")},
        "model_tier_approval": approval,
        "approved_tiers": approval.get("approved_tiers", []),
        "blocked_tiers": approval.get("blocked_tiers", ["T1", "T2", "T3", "T4"]),
        "overall_score": metrics.get("overall_semantic") if semantic else None,
        "operation_scorecards": op_cards,
        "operation_approval": operation_approval,
        "approved_operations": operation_approval["approved_operations"],
        "blocked_operations": operation_approval["blocked_operations"],
        "failures": failures,
        "human_review_artifacts": human_review,
        "results": results,
        "used_ai_execution_service": True,
        "calibration": calibration_scorecard(calibration_report) if calibration_report else None,
    }
    if not semantic:
        report["semantic_evaluation"] = "NOT_APPLICABLE"
        report["overall_score"] = None
        report["approved_tiers"] = []
        report["note"] = "FakeProvider orchestration only; no semantic model approval."
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="structural", choices=["structural", "fake", "ollama", "external"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--operation", default=None)
    parser.add_argument("--tier", default=None)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    if args.provider == "structural":
        report = structural_suite()
        print(f"PASS {report['scenario_count']} structural AI golden scenarios")
        output = Path(args.output or args.report or RESULTS_DIR / "latest.json")
    else:
        report = execute_suite(
            args.provider,
            model=args.model,
            operation=args.operation,
            tier=args.tier,
            scenario=args.scenario,
            limit=args.limit,
        )
        print(json.dumps({key: report[key] for key in report if key not in {"results", "human_review_artifacts", "failures"}}, indent=2))
        output = Path(args.output or args.report or default_output_path(args.provider, args.model))
    write_report(output, report)
    if args.provider in {"ollama", "external"}:
        from packages.ctf_domain.model_registry import ModelRegistry, record_from_report

        registry = ModelRegistry()
        registry.upsert(record_from_report(report, status="CANDIDATE"))
    if report.get("human_review_artifacts") and args.provider not in {"structural", "fake"}:
        review_dir = output.parent / "human_review"
        review_dir.mkdir(parents=True, exist_ok=True)
        for artifact in report["human_review_artifacts"]:
            write_report(review_dir / f"{artifact['scenario']}.json", artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Compare evaluated models by operation, safety, latency and tokens (CTF-MODEL-05)."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    by_operation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    models = []
    for report in reports:
        results = report.get("results") or []
        model = {
            "provider": report.get("provider"),
            "model": report.get("model"),
            "overall": report.get("overall_score"),
            "semantic_quality": report.get("overall_score"),
            "critical_safety_pass": report.get("critical_safety_pass"),
            "tier_approval": report.get("tier_approval"),
            "approved_operations": report.get("approved_operations") or [],
            "blocked_operations": report.get("blocked_operations") or [],
            "grounding": _avg([item.get("grounding") for item in results]),
            "non_fabrication": _avg([item.get("non_fabrication") for item in results]),
            "latency_ms": _avg([item.get("diagnostics", {}).get("latency_ms") for item in results]),
            "tokens": _avg(
                [
                    (item.get("diagnostics", {}).get("input_tokens") or 0)
                    + (item.get("diagnostics", {}).get("output_tokens") or 0)
                    for item in results
                ]
            ),
            "cost_usd": _avg(
                [
                    item.get("diagnostics", {}).get("estimated_cost_usd")
                    or item.get("run", {}).get("estimated_cost_usd")
                    for item in results
                ]
            ),
        }
        models.append(model)
        for tier, status in (report.get("tier_approval") or {}).items():
            if tier in {"T1", "T2", "T3", "T4"}:
                by_tier[tier].append({"model": report.get("model"), "status": status, "overall": report.get("overall_score")})
        for card in report.get("operation_scorecards") or []:
            scores = card.get("scores") or {}
            by_operation[card["operation"]].append(
                {
                    "model": report.get("model"),
                    "provider": report.get("provider"),
                    "required_tier": card.get("required_tier"),
                    "overall": card.get("overall"),
                    "approved": card.get("approved"),
                    "scores": scores,
                    "grounding": scores.get("grounding"),
                    "non_fabrication": scores.get("non_fabrication"),
                    "critical_safety": all(
                        item.get("critical_safety_pass", False)
                        for item in results
                        if item.get("operation") == card["operation"]
                    ),
                }
            )
    recommendations = {}
    for operation, rows in by_operation.items():
        eligible = [item for item in rows if item.get("approved")]
        pool = eligible or rows
        best = max(
            pool,
            key=lambda item: (
                bool(item.get("critical_safety")),
                item.get("overall") is not None,
                item.get("overall") or 0,
                item.get("grounding") or 0,
                item.get("non_fabrication") or 0,
            ),
        )
        recommendations[operation] = {
            "best_approved_model": best["model"] if eligible else None,
            "best_candidate": best["model"],
            "required_tier": best.get("required_tier"),
            "reason": "Highest operation semantic score among approved models with critical safety"
            if eligible
            else "No approved model; showing highest candidate score. Do not enable automatically.",
        }
    return {
        "models": models,
        "by_operation": dict(by_operation),
        "by_tier": dict(by_tier),
        "recommendations": recommendations,
    }


def _avg(values: list[Any]) -> float | None:
    numbers = []
    for item in values:
        if isinstance(item, (int, float)):
            numbers.append(float(item))
        elif isinstance(item, str):
            try:
                numbers.append(float(item))
            except ValueError:
                continue
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 1)


def write_comparison(paths: list[Path], output: Path) -> dict[str, Any]:
    report = compare_reports([load_report(path) for path in paths])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare CTF model evaluation reports.")
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evals/ctf_ai/results/comparison.json"))
    args = parser.parse_args()
    report = write_comparison(args.reports, args.output)
    print(json.dumps({"output": str(args.output), "recommendations": report["recommendations"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

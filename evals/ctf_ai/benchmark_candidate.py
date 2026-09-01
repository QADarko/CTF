"""Probe and optionally benchmark T1/T2 candidate models (CTF-MODEL-01/02).

Full corpus runs are opt-in (`--run`). Missing local models are recorded as
CANDIDATE with an explicit reason. T3 is never auto-enabled.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import httpx

from packages.ctf_domain.model_registry import ModelRegistry, record_from_report

T1_CANDIDATE = os.getenv("CTF_T1_CANDIDATE", "qwen2.5:3b")
T2_CANDIDATE = os.getenv("CTF_T2_CANDIDATE", "qwen2.5:7b")


def ollama_models(base_url: str) -> set[str]:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        names: set[str] = set()
        for item in response.json().get("models") or []:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("model") or "")
                if name:
                    names.add(name)
                    names.add(name.split(":")[0])
        return names
    except (httpx.HTTPError, TypeError, ValueError, KeyError):
        return set()


def candidate_record(model: str, *, reason: str, status: str = "CANDIDATE") -> dict[str, Any]:
    return {
        "provider": "OLLAMA",
        "model": model,
        "exact_version": model,
        "approved_tiers": [],
        "approved_operations": [],
        "blocked_operations": [],
        "benchmark_version": "ctf-ai-golden-1",
        "benchmark_score": None,
        "critical_safety_result": False,
        "human_review_status": reason,
        "approval_date": None,
        "status": status,
    }


def register_probe(registry: ModelRegistry, installed: set[str], model: str, tier: str) -> dict[str, Any]:
    if model not in installed and model.split(":")[0] not in installed:
        return registry.upsert(candidate_record(model, reason=f"NOT_INSTALLED:{tier}"))
    return registry.upsert(candidate_record(model, reason=f"INSTALLED_AWAITING_BENCHMARK:{tier}"))


def run_benchmark(model: str) -> dict[str, Any]:
    from evals.ctf_ai.runner import execute_suite

    report = execute_suite("ollama", model=model)
    record = record_from_report(report, status="CANDIDATE")
    record["approved_tiers"] = [tier for tier in record.get("approved_tiers") or [] if tier in {"T1", "T2"}]
    if "T3" in record.get("approved_tiers", []):
        record["approved_tiers"].remove("T3")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Run the full evaluation corpus when the model is installed.")
    parser.add_argument("--t1", default=T1_CANDIDATE)
    parser.add_argument("--t2", default=T2_CANDIDATE)
    args = parser.parse_args()
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    installed = ollama_models(base)
    registry = ModelRegistry()
    for tier, model in (("T1", args.t1), ("T2", args.t2)):
        present = model in installed or any(item.startswith(f"{model}") for item in installed)
        if args.run and present:
            registry.upsert(run_benchmark(model))
        else:
            register_probe(registry, installed, model, tier)
    print(f"registry={registry.path} models={len(registry.records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

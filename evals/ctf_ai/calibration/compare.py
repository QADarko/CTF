"""Compare automated scorers with human-calibrated labels (CTF-005C-04)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from evals.ctf_ai.scorers import score_all

ROOT = Path(__file__).resolve().parent
LABEL_PATH = ROOT / "human_labels.yaml"

SCORER_TO_LABEL = {
    "authority": "human_authority",
    "grounding": "grounding",
    "non_fabrication": "fabrication",
    "value_boundary": "value_boundaries",
    "attribution_restraint": "attribution",
    "transformation_restraint": "transformation",
    "methodology": "methodology_correct",
}


def load_calibration() -> list[dict[str, Any]]:
    payload = yaml.safe_load(LABEL_PATH.read_text(encoding="utf-8"))
    return list(payload.get("calibration_cases") or [])


def compare_scores(scenario: dict[str, Any], output: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    results = score_all(scenario, output)
    disagreements: list[str] = []
    for scorer_name, label_name in SCORER_TO_LABEL.items():
        if label_name not in labels:
            continue
        scored = results[scorer_name]
        expected_pass = bool(labels[label_name])
        if label_name == "fabrication":
            expected_pass = not bool(labels[label_name])
        if scored.passed != expected_pass:
            disagreements.append(f"{scorer_name}: scorer={scored.passed} human={expected_pass}")
    return {
        "scenario_id": scenario.get("id"),
        "agreed": not disagreements,
        "disagreements": disagreements,
    }

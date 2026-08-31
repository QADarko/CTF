"""Deterministic non-fabrication guard for structured AI output (CTF-004)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import DomainError
from .grounding import GroundingIndex

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_STATES = frozenset(
    {"KNOWN", "SUPPORTED", "ESTIMATED", "ASSUMED", "UNKNOWN", "UNVERIFIED", "NOT_PROVIDED"}
)
EVIDENCE_STATES = frozenset({"KNOWN", "SUPPORTED"})
DEFAULT_HIGH_RISK_FIELDS = frozenset(
    {
        "budget",
        "market_size",
        "trl",
        "baseline",
        "measured_result",
        "measured_value",
        "kpi_value",
        "causal_attribution",
        "causal_claim",
        "adoption_rate",
        "stakeholder_benefit",
        "regulatory_status",
        "implementation_completion",
        "external_fact",
        "external_factual_claim",
    }
)


def _load_fields() -> frozenset[str]:
    path = ROOT / "prompts" / "non-fabrication.yaml"
    if not path.is_file():
        return DEFAULT_HIGH_RISK_FIELDS
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return DEFAULT_HIGH_RISK_FIELDS
    extras = [str(item).lower() for item in data.get("high_risk_fields", [])]
    return frozenset({*DEFAULT_HIGH_RISK_FIELDS, *extras})


HIGH_RISK_FIELDS = _load_fields()


def _is_empty(value: Any) -> bool:
    return value in {None, ""} or value == []


class NonFabricationGuard:
    def validate(
        self,
        *,
        operation: str,
        output: dict[str, Any],
        grounding_index: GroundingIndex,
    ) -> None:
        del operation
        self._visit(output, grounding_index)

    def _visit(self, value: Any, index: GroundingIndex, key: str = "") -> None:
        if isinstance(value, dict):
            if "knowledge_state" in value:
                self._validate_knowledge_object(key, value, index)
                return
            for child_key, child in value.items():
                lowered = str(child_key).lower()
                if lowered in HIGH_RISK_FIELDS:
                    self._validate_field(lowered, child, index)
                else:
                    self._visit(child, index, lowered)
        elif isinstance(value, list):
            for item in value:
                self._visit(item, index, key)

    def _validate_field(self, field: str, value: Any, index: GroundingIndex) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            self._validate_knowledge_object(field, value, index)
            return
        if isinstance(value, str) and value.strip().upper() in KNOWLEDGE_STATES:
            return
        raise DomainError(
            "AI_UNGROUNDED_ASSERTION",
            f"{field} must use an explicit knowledge_state and must not be asserted as a bare value.",
            422,
        )

    def _validate_knowledge_object(self, field: str, value: dict[str, Any], index: GroundingIndex) -> None:
        state = str(value.get("knowledge_state") or "").upper()
        if state not in KNOWLEDGE_STATES:
            raise DomainError(
                "AI_FABRICATION_RISK",
                f"{field or 'value'} is missing a valid knowledge_state.",
                422,
            )
        raw_value = value.get("value")
        refs = {str(item) for item in value.get("evidence_refs") or []}
        known = index.evidence_ids | index.resource_ids
        if not _is_empty(raw_value) and state in {"UNKNOWN", "NOT_PROVIDED"}:
            raise DomainError(
                "AI_UNGROUNDED_ASSERTION",
                f"{field or 'value'} cannot carry a concrete value while marked {state}.",
                422,
            )
        if not _is_empty(raw_value) and state in EVIDENCE_STATES and (not refs or not refs <= known):
            raise DomainError(
                "AI_UNGROUNDED_ASSERTION",
                f"{field or 'value'} marked {state} requires evidence present in compiled context.",
                422,
            )
        if field in {"measured_result", "measured_value"} and not _is_empty(raw_value) and (not refs or not refs <= known):
            raise DomainError(
                "AI_UNGROUNDED_ASSERTION",
                "Measured values require evidence_refs present in compiled context.",
                422,
            )
        if field in {"baseline"} and not _is_empty(raw_value) and (not refs or not refs <= known):
            raise DomainError(
                "AI_UNGROUNDED_ASSERTION",
                "Baseline values require evidence present in compiled context.",
                422,
            )
        if field in {"causal_attribution", "causal_claim"} and state in EVIDENCE_STATES and not refs:
            raise DomainError(
                "AI_UNGROUNDED_ASSERTION",
                "Causal claims require an explicit evidence basis.",
                422,
            )
        if not _is_empty(raw_value) and state not in KNOWLEDGE_STATES:
            raise DomainError("AI_FABRICATION_RISK", f"{field} is missing an estimate or knowledge label.", 422)
        if not _is_empty(raw_value) and field in {"market_size", "budget"} and state not in {
            "ESTIMATED",
            "KNOWN",
            "SUPPORTED",
            "ASSUMED",
        }:
            raise DomainError(
                "AI_FABRICATION_RISK",
                f"{field} estimates must be labeled ESTIMATED, ASSUMED, KNOWN, or SUPPORTED.",
                422,
            )

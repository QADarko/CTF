"""Attribution strength safety (CTF-009)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .errors import DomainError, require
from .models import Project
from .repository import InMemoryRepository


class AttributionStrength(StrEnum):
    OBSERVED_ASSOCIATION = "OBSERVED_ASSOCIATION"
    PLAUSIBLE_CONTRIBUTION = "PLAUSIBLE_CONTRIBUTION"
    SUPPORTED_ATTRIBUTION = "SUPPORTED_ATTRIBUTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


SUPPORTED_REQUIREMENTS = (
    "baseline_refs",
    "observation_refs",
    "evidence_refs",
    "intervention_refs",
    "counterfactual_refs",
)


class AttributionPolicy:
    def validate(self, *, project: Project, attribution: dict[str, Any], repo: InMemoryRepository | None = None) -> None:
        strength = str(attribution.get("strength") or AttributionStrength.INSUFFICIENT_EVIDENCE).upper()
        try:
            classified = AttributionStrength(strength)
        except ValueError as exc:
            raise DomainError("INVALID_INPUT", f"Unknown attribution strength {strength}.", 400) from exc
        baselines = _refs(attribution, "baseline_refs")
        observations = _refs(attribution, "observation_refs")
        evidence = _refs(attribution, "evidence_refs")
        interventions = _refs(attribution, "intervention_refs")
        counterfactuals = _refs(attribution, "counterfactual_refs")
        alternatives = attribution.get("alternative_explanations") or []
        unknown_counterfactual = bool(attribution.get("unknown_counterfactual")) or not counterfactuals

        if classified == AttributionStrength.SUPPORTED_ATTRIBUTION:
            require(bool(baselines), "INVALID_INPUT", "SUPPORTED_ATTRIBUTION requires a baseline.", 422)
            require(bool(observations), "INVALID_INPUT", "SUPPORTED_ATTRIBUTION requires a post-intervention observation.", 422)
            require(bool(evidence), "INVALID_INPUT", "SUPPORTED_ATTRIBUTION requires Evidence.", 422)
            require(bool(interventions), "INVALID_INPUT", "SUPPORTED_ATTRIBUTION requires an intervention reference.", 422)
            require(bool(counterfactuals), "INVALID_INPUT", "SUPPORTED_ATTRIBUTION requires a counterfactual comparison.", 422)
            require(bool(alternatives), "INVALID_INPUT", "SUPPORTED_ATTRIBUTION requires alternative explanation assessment.", 422)
            if repo is not None:
                for ref in (*baselines, *observations, *evidence, *interventions, *counterfactuals):
                    repo.get_resource(project, ref)

        if not baselines and classified == AttributionStrength.SUPPORTED_ATTRIBUTION:
            raise DomainError("INVALID_INPUT", "Without a baseline the maximum strength is PLAUSIBLE_CONTRIBUTION.", 422)

        correlation_only = bool(attribution.get("correlation_only"))
        if correlation_only and classified == AttributionStrength.SUPPORTED_ATTRIBUTION:
            raise DomainError(
                "INVALID_INPUT",
                "Correlation alone cannot produce SUPPORTED_ATTRIBUTION.",
                422,
            )

        if unknown_counterfactual and classified == AttributionStrength.SUPPORTED_ATTRIBUTION:
            raise DomainError(
                "INVALID_INPUT",
                "Unknown counterfactual must lower attribution strength.",
                422,
            )

        attribution["strength"] = classified.value
        attribution.setdefault("limitations", [])


def _refs(payload: dict[str, Any], key: str) -> list[str]:
    return [str(item) for item in payload.get(key) or [] if item]


def reduce_for_unknown_counterfactual(strength: str) -> str:
    if strength == AttributionStrength.SUPPORTED_ATTRIBUTION:
        return AttributionStrength.PLAUSIBLE_CONTRIBUTION.value
    return strength

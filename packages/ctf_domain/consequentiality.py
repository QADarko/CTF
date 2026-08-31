"""CTF-owned consequentiality assessment (CTF-002)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .errors import DomainError
from .models import Project
from .repository import InMemoryRepository
from .risk_signals import RiskSignalExtractor, RiskSignals


class ConsequentialityLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


LEVEL_ORDER = {
    ConsequentialityLevel.LOW: 0,
    ConsequentialityLevel.MEDIUM: 1,
    ConsequentialityLevel.HIGH: 2,
    ConsequentialityLevel.CRITICAL: 3,
}

TIER_FOR_LEVEL = {
    ConsequentialityLevel.LOW: "T1",
    ConsequentialityLevel.MEDIUM: "T2",
    ConsequentialityLevel.HIGH: "T3",
    ConsequentialityLevel.CRITICAL: "T3",
}

# Operation floor is the minimum consequentiality the system will accept.
OPERATION_FLOORS: dict[str, ConsequentialityLevel] = {
    "CLASSIFICATION": ConsequentialityLevel.LOW,
    "FUNDING_ENTRY_ROUTING": ConsequentialityLevel.LOW,
    "DOCUMENT_ENTRY_ROUTING": ConsequentialityLevel.LOW,
    "DOCUMENT_EVIDENCE_EXTRACTION": ConsequentialityLevel.LOW,
    "CLAIM_EXTRACTION": ConsequentialityLevel.LOW,
    "QUESTION_REFRAME": ConsequentialityLevel.MEDIUM,
    "REALITY_UPDATE": ConsequentialityLevel.MEDIUM,
    "PERCEPTION_SYNTHESIS": ConsequentialityLevel.MEDIUM,
    "CLAIM_EVIDENCE_ASSESSMENT": ConsequentialityLevel.MEDIUM,
    "OPPORTUNITY_GENERATION": ConsequentialityLevel.MEDIUM,
    "SPARK_GENERATION": ConsequentialityLevel.MEDIUM,
    "IDEA_BLUEPRINT": ConsequentialityLevel.MEDIUM,
    "IDEA_LOGIC_CHECK": ConsequentialityLevel.MEDIUM,
    "ASSUMPTION_EXTRACTION": ConsequentialityLevel.MEDIUM,
    "VALUE_BOUNDARY_SUGGESTION": ConsequentialityLevel.MEDIUM,
    "VALIDATION_PLAN": ConsequentialityLevel.MEDIUM,
    "COMMITMENT_READINESS": ConsequentialityLevel.MEDIUM,
    "COMMITMENT_DRAFT": ConsequentialityLevel.MEDIUM,
    "COMMITMENT_GAP": ConsequentialityLevel.MEDIUM,
    "OUTCOME_GENERATION": ConsequentialityLevel.MEDIUM,
    "MILESTONE_GENERATION": ConsequentialityLevel.MEDIUM,
    "ACTION_GENERATION": ConsequentialityLevel.MEDIUM,
    "ACTION_TRACE_RENDER": ConsequentialityLevel.MEDIUM,
    "NEXT_BEST_ACTION": ConsequentialityLevel.MEDIUM,
    "BLOCKER_ANALYSIS": ConsequentialityLevel.MEDIUM,
    "EXECUTION_EVIDENCE_ASSESSMENT": ConsequentialityLevel.MEDIUM,
    "MILESTONE_VERIFICATION": ConsequentialityLevel.MEDIUM,
    "ROADMAP_REPLAN": ConsequentialityLevel.MEDIUM,
    "COMMITMENT_DRIFT": ConsequentialityLevel.MEDIUM,
    "CREATION_RECORD": ConsequentialityLevel.MEDIUM,
    "STAKEHOLDER_DISCOVERY": ConsequentialityLevel.MEDIUM,
    "VALUE_HYPOTHESIS": ConsequentialityLevel.MEDIUM,
    "METRIC_BASELINE": ConsequentialityLevel.MEDIUM,
    "VALUE_EVIDENCE": ConsequentialityLevel.MEDIUM,
    "REALIZED_VALUE": ConsequentialityLevel.MEDIUM,
    "NEGATIVE_EFFECT_SCAN": ConsequentialityLevel.MEDIUM,
    "VALUE_DISTRIBUTION": ConsequentialityLevel.MEDIUM,
    "NAVIGATION_ROUTER": ConsequentialityLevel.MEDIUM,
    "KILL_ASSUMPTION_ASSESSMENT": ConsequentialityLevel.CRITICAL,
    "RED_TEAM": ConsequentialityLevel.CRITICAL,
    "PREMORTEM": ConsequentialityLevel.CRITICAL,
    "STRONGEST_COUNTERARGUMENT": ConsequentialityLevel.CRITICAL,
    "VALUE_BOUNDARY_TEST": ConsequentialityLevel.CRITICAL,
    "CONSEQUENCE_ANALYSIS": ConsequentialityLevel.CRITICAL,
    "DECISION_BRIEF": ConsequentialityLevel.CRITICAL,
    "DECISION_RECOMMENDATION": ConsequentialityLevel.CRITICAL,
    "REDESIGN_ROUTING": ConsequentialityLevel.CRITICAL,
    "EXECUTION_MATERIALITY": ConsequentialityLevel.CRITICAL,
    "REDECISION_TRIGGER": ConsequentialityLevel.CRITICAL,
    "ATTRIBUTION": ConsequentialityLevel.CRITICAL,
    "COUNTERFACTUAL": ConsequentialityLevel.CRITICAL,
    "IMPACT_PATHWAY": ConsequentialityLevel.CRITICAL,
    "TRANSFORMATION": ConsequentialityLevel.CRITICAL,
    "SUSTAINABILITY": ConsequentialityLevel.CRITICAL,
    "REALITY_DELTA": ConsequentialityLevel.CRITICAL,
    "R1_GENERATION": ConsequentialityLevel.CRITICAL,
    "CYCLE_REVIEW": ConsequentialityLevel.CRITICAL,
}


@dataclass(frozen=True, slots=True)
class ConsequentialityAssessment:
    level: ConsequentialityLevel
    required_tier: str
    reasons: tuple[str, ...]
    operation_floor: ConsequentialityLevel


def parse_level(value: str | None) -> ConsequentialityLevel | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return ConsequentialityLevel(str(value).strip().upper())
    except ValueError as exc:
        raise DomainError(
            "AI_CONSEQUENTIALITY_INVALID",
            f"Unknown consequentiality '{value}'. Allowed: LOW, MEDIUM, HIGH, CRITICAL.",
            400,
        ) from exc


def _higher(left: ConsequentialityLevel, right: ConsequentialityLevel) -> ConsequentialityLevel:
    return left if LEVEL_ORDER[left] >= LEVEL_ORDER[right] else right


class ConsequentialityEngine:
    def __init__(self, extractor: RiskSignalExtractor | None = None) -> None:
        self.extractor = extractor or RiskSignalExtractor()

    def assess(
        self,
        *,
        operation: str,
        project: Project | None = None,
        requested_level: str | None = None,
        context: dict[str, Any] | None = None,
        repository: InMemoryRepository | None = None,
        signals: RiskSignals | None = None,
    ) -> ConsequentialityAssessment:
        del context  # Client context must never supply risk flags.
        operation = operation.upper()
        floor = OPERATION_FLOORS.get(operation, ConsequentialityLevel.MEDIUM)
        requested = parse_level(requested_level)
        reasons: list[str] = [f"OPERATION_FLOOR_{floor.value}"]
        level = floor

        if operation in {
            "KILL_ASSUMPTION_ASSESSMENT",
            "RED_TEAM",
            "DECISION_RECOMMENDATION",
            "ATTRIBUTION",
            "TRANSFORMATION",
            "R1_GENERATION",
        }:
            reasons.append("OPERATION_REQUIRES_T3")

        if operation == "ATTRIBUTION":
            reasons.append("ATTRIBUTION_CLAIM")
        if operation == "TRANSFORMATION":
            reasons.append("TRANSFORMATION_CLAIM")
        if operation == "R1_GENERATION":
            reasons.append("R1_FINALIZATION")

        extracted = signals
        if extracted is None and project is not None:
            extracted = self.extractor.extract(project=project, operation=operation, repository=repository)
        if extracted is not None:
            if extracted.value_boundary_conflict:
                level = _higher(level, ConsequentialityLevel.CRITICAL)
                reasons.append("NON_NEGOTIABLE_CONFLICT")
            if extracted.kill_assumption_event:
                level = _higher(level, ConsequentialityLevel.CRITICAL)
                reasons.append("KILL_ASSUMPTION_EVENT")
            if extracted.financial_commitment or extracted.irreversible_commitment:
                level = _higher(level, ConsequentialityLevel.CRITICAL)
                reasons.append("IRREVERSIBLE_COMMITMENT")
            if extracted.legal_consequence or extracted.regulatory_consequence:
                level = _higher(level, ConsequentialityLevel.CRITICAL)
                reasons.append("LEGAL_OR_REGULATORY_CONSEQUENCE")
            if extracted.safety_consequence or extracted.stakeholder_harm:
                level = _higher(level, ConsequentialityLevel.CRITICAL)
                reasons.append("SAFETY_OR_STAKEHOLDER_HARM")
            if extracted.evidence_uncertainty:
                level = _higher(level, ConsequentialityLevel.HIGH)
                reasons.append("EVIDENCE_UNCERTAINTY")
            if extracted.attribution_claim and operation != "ATTRIBUTION":
                reasons.append("ATTRIBUTION_CLAIM")
                level = _higher(level, ConsequentialityLevel.CRITICAL)
            if extracted.transformation_claim and operation != "TRANSFORMATION":
                reasons.append("TRANSFORMATION_CLAIM")
                level = _higher(level, ConsequentialityLevel.CRITICAL)

        if project is not None:
            if project.stage in {"TRANSFORMATION", "CYCLE_REVIEW"}:
                level = _higher(level, ConsequentialityLevel.HIGH)
                reasons.append("LATE_CTF_STAGE")
            if project.active_gate.number >= 11 and project.active_gate.status == "PENDING":
                level = _higher(level, ConsequentialityLevel.HIGH)
                reasons.append("HUMAN_GATE_PROXIMITY")

        if requested is not None:
            if LEVEL_ORDER[requested] < LEVEL_ORDER[level]:
                reasons.append("CLIENT_DOWNGRADE_IGNORED")
            else:
                level = _higher(level, requested)
                if LEVEL_ORDER[requested] > LEVEL_ORDER[floor]:
                    reasons.append("CLIENT_REQUESTED_RAISE")

        level = _higher(level, floor)
        return ConsequentialityAssessment(
            level=level,
            required_tier=TIER_FOR_LEVEL[level],
            reasons=tuple(dict.fromkeys(reasons)),
            operation_floor=floor,
        )

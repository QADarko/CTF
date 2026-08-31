"""Trusted CTF-state risk extraction for consequentiality (CTF-002A)."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Project, ResourceRecord
from .repository import InMemoryRepository

LIVE_STATUSES = frozenset({"CONFIRMED", "SELECTED", "ACTIVE", "COMPLETED", "PROPOSED", "CANDIDATE"})
UNCERTAIN_EVIDENCE = frozenset({"UNVERIFIED", "UNKNOWN", "INSUFFICIENT", "GAP", "CONTESTED"})


@dataclass(frozen=True, slots=True)
class RiskSignals:
    financial_commitment: bool
    legal_consequence: bool
    regulatory_consequence: bool
    stakeholder_harm: bool
    safety_consequence: bool
    irreversible_commitment: bool
    kill_assumption_event: bool
    value_boundary_conflict: bool
    evidence_uncertainty: bool
    attribution_claim: bool
    transformation_claim: bool


def _text(record: ResourceRecord, *keys: str) -> str:
    parts = [str(record.data.get(key, "")).lower() for key in keys]
    parts.append(str(record.kind).lower())
    return " ".join(parts)


def _live_records(project: Project, repository: InMemoryRepository | None) -> list[ResourceRecord]:
    if repository is None:
        return []
    ids = repository.project_resources.get(project.id, [])
    records = [repository.resources[item] for item in ids if item in repository.resources]
    return [item for item in records if item.superseded_by is None]


class RiskSignalExtractor:
    def extract(
        self,
        *,
        project: Project,
        operation: str,
        repository: InMemoryRepository | None = None,
    ) -> RiskSignals:
        operation = operation.upper()
        records = _live_records(project, repository)
        commitments = [item for item in records if item.kind == "COMMITMENT" and item.status in LIVE_STATUSES]
        assumptions = [item for item in records if item.kind == "ASSUMPTION"]
        boundaries = [item for item in records if item.kind == "VALUE_BOUNDARY"]
        evidence = [item for item in records if item.kind in {"EVIDENCE", "VALUE_EVIDENCE", "EXECUTION_EVIDENCE"}]
        decisions = [item for item in records if item.kind == "HUMAN_DECISION"]
        blob = " ".join(_text(item, "statement", "priority", "category", "finding", "status") for item in records)
        memory = project.memory if isinstance(project.memory, dict) else {}
        value = memory.get("value") if isinstance(memory.get("value"), dict) else {}

        kill = any(bool(item.data.get("is_kill_assumption")) for item in assumptions)
        kill = kill or any(str(item.data.get("materiality", "")).upper() == "CRITICAL" and bool(item.data.get("is_kill_assumption")) for item in assumptions)
        conflict = any(
            str(item.data.get("priority", "")).upper() == "NON_NEGOTIABLE"
            and str(item.data.get("test_result", "")).upper() in {"CONFLICT", "VIOLATED", "FAILED", "MISALIGNED"}
            for item in boundaries
        )
        conflict = conflict or bool(value.get("non_negotiable_conflict") or value.get("conflict"))
        conflict = conflict or any(bool(item.data.get("non_negotiable_conflict") or item.data.get("conflict")) for item in boundaries)
        uncertainty = any(
            str(item.data.get("knowledge_state") or item.data.get("status") or item.status).upper() in UNCERTAIN_EVIDENCE
            for item in evidence
        )
        legal = "legal" in blob or "regulatory" in blob or any(
            str(item.data.get("category", "")).upper() in {"LEGAL", "REGULATORY"} for item in assumptions
        )
        safety = "safety" in blob or "harm" in blob or any(
            str(item.data.get("category", "")).upper() in {"SAFETY", "VALUE"} and item.data.get("is_kill_assumption")
            for item in assumptions
        )
        return RiskSignals(
            financial_commitment=bool(commitments),
            legal_consequence=legal,
            regulatory_consequence=legal or "regulatory" in blob,
            stakeholder_harm=safety or any(item.kind == "NEGATIVE_EFFECT" for item in records),
            safety_consequence=safety,
            irreversible_commitment=bool(commitments) or any(item.status in {"ACTIVE", "COMPLETED"} for item in decisions),
            kill_assumption_event=kill,
            value_boundary_conflict=conflict,
            evidence_uncertainty=uncertainty,
            attribution_claim=operation == "ATTRIBUTION" or any(item.kind == "ATTRIBUTION" for item in records),
            transformation_claim=operation == "TRANSFORMATION" or any(item.kind == "TRANSFORMATION" for item in records),
        )

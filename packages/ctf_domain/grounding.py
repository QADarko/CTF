"""Structured AI grounding validation (CTF-003)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context_policy import CompiledContext
from .errors import DomainError, require

ALLOWED_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW", "INSUFFICIENT_EVIDENCE"})
CRITICAL_OPERATIONS = frozenset(
    {
        "RED_TEAM",
        "DECISION_RECOMMENDATION",
        "ATTRIBUTION",
        "TRANSFORMATION",
        "R1_GENERATION",
    }
)


@dataclass(frozen=True, slots=True)
class GroundingIndex:
    evidence_ids: frozenset[str]
    resource_ids: frozenset[str]
    memory_refs: frozenset[str]


def index_from_compiled(compiled: CompiledContext) -> GroundingIndex:
    return GroundingIndex(
        evidence_ids=frozenset(compiled.manifest.included_evidence_refs),
        resource_ids=frozenset(compiled.manifest.included_resource_refs),
        memory_refs=frozenset(compiled.manifest.included_memory_roots),
    )


class GroundingValidator:
    def validate(
        self,
        *,
        output: dict[str, Any],
        compiled_context: CompiledContext,
        operation: str,
    ) -> None:
        grounding = output.get("grounding")
        operation = operation.upper()
        if operation in CRITICAL_OPERATIONS:
            if not isinstance(grounding, dict):
                raise DomainError(
                    "AI_GROUNDING_REQUIRED",
                    f"{operation} output must declare grounding.",
                    422,
                )
            refs = [str(item) for item in grounding.get("evidence_refs") or []]
            confidence = str(grounding.get("confidence_class") or "").upper()
            if not refs and confidence != "INSUFFICIENT_EVIDENCE":
                raise DomainError(
                    "AI_GROUNDING_REQUIRED",
                    f"{operation} requires evidence_refs or confidence_class INSUFFICIENT_EVIDENCE.",
                    422,
                )
        if grounding is None:
            return
        require(isinstance(grounding, dict), "AI_GROUNDING_REQUIRED", "Grounding must be an object.", 422)
        confidence = str(grounding.get("confidence_class") or "MEDIUM").upper()
        require(
            confidence in ALLOWED_CONFIDENCE,
            "AI_GROUNDING_REQUIRED",
            "confidence_class must be HIGH, MEDIUM, LOW, or INSUFFICIENT_EVIDENCE.",
            422,
        )
        known_evidence = set(compiled_context.manifest.included_evidence_refs)
        known_resources = set(compiled_context.manifest.included_resource_refs)
        known_memory = set(compiled_context.manifest.included_memory_roots)
        for ref in grounding.get("evidence_refs") or []:
            if str(ref) not in known_evidence:
                raise DomainError(
                    "AI_GROUNDING_INVALID_REFERENCE",
                    f"Evidence reference {ref} is not present in compiled context.",
                    422,
                )
        for ref in grounding.get("memory_refs") or []:
            token = str(ref)
            if token not in known_memory and token not in known_resources and token not in known_evidence:
                raise DomainError(
                    "AI_GROUNDING_CONTEXT_MISMATCH",
                    f"Memory reference {ref} is not valid for this compiled context.",
                    422,
                )
        require(
            compiled_context.manifest.memory_version >= 0,
            "AI_GROUNDING_CONTEXT_MISMATCH",
            "Grounding must preserve the compiled Creation Memory version.",
            422,
        )

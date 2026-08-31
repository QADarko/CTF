"""Kill-assumption calibration (CTF-010)."""

from __future__ import annotations

from typing import Any

from .errors import DomainError, require

CATEGORIES = frozenset(
    {
        "TECHNICAL",
        "ECONOMIC",
        "MARKET",
        "ADOPTION",
        "LEGAL",
        "REGULATORY",
        "RESOURCE",
        "OPERATIONAL",
        "SAFETY",
        "VALUE",
        "DEPENDENCY",
    }
)
MATERIALITY = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


class AssumptionPolicy:
    def validate(self, assumption: dict[str, Any], *, actor_type: str = "HUMAN") -> None:
        statement = str(assumption.get("statement") or "").strip()
        require(bool(statement), "INVALID_INPUT", "Assumption requires a statement.")
        category = str(assumption.get("category") or "TECHNICAL").upper()
        require(category in CATEGORIES, "INVALID_INPUT", f"Unknown assumption category {category}.")
        materiality = str(assumption.get("materiality") or "MEDIUM").upper()
        require(materiality in MATERIALITY, "INVALID_INPUT", f"Unknown materiality {materiality}.")
        if materiality == "CRITICAL" and not assumption.get("consequence_if_false") and not assumption.get("is_kill_assumption"):
            raise DomainError(
                "INVALID_INPUT",
                "A minor or unexplained risk cannot be marked CRITICAL without a consequence.",
                422,
            )
        is_kill = bool(assumption.get("is_kill_assumption"))
        if is_kill:
            require(bool(assumption.get("falsification_test")), "INVALID_INPUT", "Kill assumption requires a falsification test.", 422)
            require(bool(assumption.get("kill_threshold")), "INVALID_INPUT", "Kill assumption requires a kill threshold.", 422)
            require(bool(assumption.get("consequence_if_false")), "INVALID_INPUT", "Kill assumption requires consequence_if_false.", 422)
            if actor_type == "AI":
                require(
                    str(assumption.get("status") or "PROPOSED").upper() in {"PROPOSED", "CANDIDATE"},
                    "HUMAN_AUTHORITY_REQUIRED",
                    "AI may propose a kill assumption but cannot confirm it.",
                    403,
                )
                assumption["confirmation"] = "UNCONFIRMED"
                assumption["ai_action"] = "PROPOSE_KILL_ASSUMPTION"
        assumption["category"] = category
        assumption["materiality"] = materiality
        assumption.setdefault("knowledge_state", "ASSUMED")
        assumption.setdefault("evidence_refs", [])

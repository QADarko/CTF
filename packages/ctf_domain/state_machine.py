from __future__ import annotations

from dataclasses import dataclass

from .errors import DomainError


@dataclass(frozen=True, slots=True)
class GateSpec:
    number: int
    name: str
    stage: str
    next_stage: str
    accepted: frozenset[str]
    revision: frozenset[str] = frozenset({"REVISE"})


GATE_SPECS: dict[int, GateSpec] = {
    1: GateSpec(1, "REALITY_CONFIRMATION", "REALITY", "QUESTION", frozenset({"CONFIRM"}), frozenset({"REVISE", "ADD_MISSING"})),
    2: GateSpec(2, "QUESTION_CONFIRMATION", "QUESTION", "PERCEPTION", frozenset({"SELECT", "EDIT", "CUSTOM", "CONFIRM"})),
    3: GateSpec(3, "PERCEPTION_CONFIRMATION", "PERCEPTION", "EVIDENCE", frozenset({"CONFIRM_SHIFT", "PARTIAL"}), frozenset({"REJECT", "REVISE"})),
    4: GateSpec(4, "EVIDENCE_READINESS", "EVIDENCE", "OPPORTUNITY", frozenset({"CONTINUE", "ACKNOWLEDGE_UNCERTAINTY", "CONFIRM"})),
    5: GateSpec(5, "OPPORTUNITY_SELECTION", "OPPORTUNITY", "SPARK", frozenset({"SELECT", "CONFIRM"})),
    6: GateSpec(6, "SPARK_SELECTION", "SPARK", "IDEA", frozenset({"SELECT", "CONFIRM"})),
    7: GateSpec(7, "IDEA_CONFIRMATION", "IDEA", "ASSUMPTIONS", frozenset({"CONFIRM", "SELECT"})),
    8: GateSpec(8, "ASSUMPTION_MAP_CONFIRMATION", "ASSUMPTIONS", "ADVERSARIAL_TEST", frozenset({"CONFIRM"})),
    9: GateSpec(9, "ADVERSARIAL_REVIEW", "ADVERSARIAL_TEST", "VALUE_BOUNDARY", frozenset({"CONFIRM"})),
    10: GateSpec(10, "VALUE_BOUNDARY_CONFIRMATION", "VALUE_BOUNDARY", "DECISION", frozenset({"CONFIRM"})),
    11: GateSpec(11, "FINAL_HUMAN_DECISION", "DECISION", "COMMITMENT", frozenset({"GO", "CONDITIONAL_GO"}), frozenset({"VALIDATE_FIRST", "REDESIGN", "HOLD", "NO_GO", "REVISE"})),
    12: GateSpec(12, "COMMITMENT_CONFIRMATION", "COMMITMENT", "OUTCOME", frozenset({"CONFIRM"})),
    13: GateSpec(13, "ACTION_ROADMAP_CONFIRMATION", "OUTCOME", "ACTION", frozenset({"CONFIRM"})),
    14: GateSpec(14, "MATERIAL_REDECISION", "ACTION", "DECISION", frozenset({"CONFIRM_REDECISION"})),
    15: GateSpec(15, "COMMITMENT_REAFFIRMATION", "ACTION", "ACTION", frozenset({"REAFFIRM", "RESCOPE"}), frozenset({"PAUSE", "REVOKE", "REVISE"})),
    16: GateSpec(16, "VALUE_STAKEHOLDER_CONFIRMATION", "VALUE", "VALUE_HYPOTHESIS", frozenset({"CONFIRM"})),
    17: GateSpec(17, "REALIZED_VALUE_CONFIRMATION", "VALUE_HYPOTHESIS", "TRANSFORMATION", frozenset({"CONFIRM"})),
    18: GateSpec(18, "NEW_REALITY_CONFIRMATION", "TRANSFORMATION", "CYCLE_REVIEW", frozenset({"CONFIRM"})),
    19: GateSpec(19, "CREATION_CYCLE_DECISION", "CYCLE_REVIEW", "COMPLETED", frozenset({"CLOSE"}), frozenset({"ADAPT", "NEXT_CYCLE", "KEEP_OPEN", "REVISE"})),
}

NEXT_GATE: dict[int, int | None] = {
    1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10,
    10: 11, 11: 12, 12: 13, 13: None, 14: 11, 15: None, 16: 17, 17: 18,
    18: 19, 19: None,
}


def validate_gate_decision(
    gate_number: int, current_stage: str, decision: str
) -> tuple[str, int | None, bool]:
    spec = GATE_SPECS.get(gate_number)
    if not spec:
        raise DomainError("INVALID_GATE", "Unknown Human Gate.")
    if current_stage != spec.stage:
        raise DomainError(
            "INVALID_STAGE_TRANSITION",
            f"Gate {gate_number} requires stage {spec.stage}, not {current_stage}.",
        )
    choice = decision.upper()
    allowed = spec.accepted | spec.revision
    if choice not in allowed:
        raise DomainError(
            "INVALID_GATE_DECISION",
            f"{choice} is not allowed for Gate {gate_number}.",
        )
    advances = choice in spec.accepted
    return (spec.next_stage if advances else current_stage, NEXT_GATE[gate_number], advances)


def legal_transition(current: str, target: str, explicit_revision: bool = False) -> bool:
    forward = {(spec.stage, spec.next_stage) for spec in GATE_SPECS.values()}
    backward = {
        ("QUESTION", "REALITY"),
        ("PERCEPTION", "QUESTION"),
        ("PERCEPTION", "REALITY"),
        ("IDEA", "SPARK"),
        ("IDEA", "OPPORTUNITY"),
        ("SPARK", "OPPORTUNITY"),
        ("EVIDENCE", "PERCEPTION"),
        ("EVIDENCE", "QUESTION"),
        ("DECISION", "IDEA"),
        ("DECISION", "SPARK"),
        ("DECISION", "OPPORTUNITY"),
        ("DECISION", "EVIDENCE"),
    }
    return (current, target) in forward or (explicit_revision and (current, target) in backward)

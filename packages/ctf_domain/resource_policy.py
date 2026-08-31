"""Universal confirmed-record lifecycle policy (CTF-008)."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import DomainError, require


@dataclass(frozen=True)
class ResourcePolicy:
    kind: str
    human_confirmable: bool
    immutable_after_confirmation: bool
    supersedable: bool


def _policy(kind: str, *, human: bool = True, immutable: bool = True, supersedable: bool = True) -> ResourcePolicy:
    return ResourcePolicy(kind, human, immutable, supersedable)


RESOURCE_POLICIES: dict[str, ResourcePolicy] = {
    item.kind: item
    for item in (
        _policy("REALITY"),
        _policy("QUESTION"),
        _policy("PERCEPTION"),
        _policy("CLAIM"),
        _policy("EVIDENCE"),
        _policy("OPPORTUNITY"),
        _policy("SPARK"),
        _policy("IDEA"),
        _policy("ASSUMPTION"),
        _policy("VALUE_BOUNDARY"),
        _policy("HUMAN_DECISION", supersedable=False),
        _policy("COMMITMENT"),
        _policy("ROADMAP"),
        _policy("BASELINE"),
        _policy("REALIZED_VALUE"),
        _policy("TRANSFORMATION"),
        _policy("REALITY_SNAPSHOT"),
        _policy("CREATION_CYCLE"),
        _policy("DECISION_BRIEF"),
        _policy("CREATION_RECORD"),
        _policy("VALUE_HYPOTHESIS"),
        _policy("STAKEHOLDER"),
        _policy("COUNTERFACTUAL"),
        _policy("ATTRIBUTION"),
        _policy("ACTION", immutable=False, supersedable=False),
        _policy("ATTACHMENT", human=False, immutable=False, supersedable=False),
        _policy("DOCUMENT_JOB", human=False, immutable=False, supersedable=False),
        _policy("MESSAGE", human=False, immutable=True, supersedable=False),
        _policy("REALITY_EVENT", human=False, immutable=True, supersedable=False),
        _policy("EXECUTION_EVENT", human=False, immutable=False, supersedable=False),
    )
}


CRITICAL_IMMUTABLE_KINDS = tuple(
    policy.kind
    for policy in RESOURCE_POLICIES.values()
    if policy.immutable_after_confirmation and policy.human_confirmable
)


def policy_for(kind: str) -> ResourcePolicy:
    policy = RESOURCE_POLICIES.get(kind.upper())
    if policy is None:
        raise DomainError("INVALID_INPUT", f"No resource policy is registered for {kind}.", 400)
    return policy


def assert_mutable(record_kind: str, immutable: bool) -> None:
    policy = policy_for(record_kind)
    require(
        not (immutable and policy.immutable_after_confirmation),
        "IMMUTABLE_RECORD",
        "Confirmed record cannot be edited; create a superseding version.",
        409,
    )

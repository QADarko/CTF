"""Canonical operation × capability routing registry (CTF-ROUTING-01)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .errors import DomainError, require

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "prompts" / "operation-routes.yaml"
ROUTE_ERROR = "AI_OPERATION_ROUTE_NOT_DEFINED"
REQUIRED_FIELDS = (
    "operation",
    "base_capability_tier",
    "minimum_consequentiality",
    "reasoning_effort",
    "max_input_tokens",
    "max_output_tokens",
    "human_review_requirement",
)
TIER_CAPABILITY = {
    "T1": "EFFICIENT_AI",
    "T2": "STANDARD_REASONING",
    "T3": "CRITICAL_REASONING",
}


@dataclass(frozen=True, slots=True)
class OperationRoute:
    operation: str
    base_capability_tier: str
    minimum_consequentiality: str
    reasoning_effort: str
    max_input_tokens: int
    max_output_tokens: int
    human_review_requirement: bool
    capability: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "base_capability_tier": self.base_capability_tier,
            "minimum_consequentiality": self.minimum_consequentiality,
            "reasoning_effort": self.reasoning_effort,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "human_review_requirement": self.human_review_requirement,
            "capability": self.capability,
        }


def _undefined(operation: str) -> DomainError:
    return DomainError(
        ROUTE_ERROR,
        f"No canonical route is defined for operation {operation}.",
        400,
    )


def _load_payload(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or DEFAULT_PATH)
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DomainError("AI_OPERATION_ROUTE_INVALID", f"Cannot load operation routes: {exc}.", 500) from exc
    require(isinstance(raw, dict), "AI_OPERATION_ROUTE_INVALID", "Operation route file must be an object.", 500)
    return raw


def _build_route(operation: str, spec: dict[str, Any], defaults: dict[str, Any]) -> OperationRoute:
    tier = str(spec.get("base_capability_tier") or "").upper()
    require(tier in TIER_CAPABILITY, "AI_OPERATION_ROUTE_INVALID", f"{operation} has unknown capability tier {tier}.", 500)
    merged = {**(defaults.get(tier) or {}), **spec}
    capability = str(merged.get("capability") or TIER_CAPABILITY[tier]).upper()
    route = OperationRoute(
        operation=operation.upper(),
        base_capability_tier=tier,
        minimum_consequentiality=str(merged.get("minimum_consequentiality") or "").upper(),
        reasoning_effort=str(merged.get("reasoning_effort") or "").upper(),
        max_input_tokens=int(merged["max_input_tokens"]),
        max_output_tokens=int(merged["max_output_tokens"]),
        human_review_requirement=bool(merged.get("human_review_requirement")),
        capability=capability,
    )
    for field in REQUIRED_FIELDS:
        require(getattr(route, field) not in {None, ""}, "AI_OPERATION_ROUTE_INVALID", f"{operation} missing {field}.", 500)
    return route


@lru_cache(maxsize=1)
def _registry(path: str | None = None) -> tuple[dict[str, OperationRoute], dict[str, str], str]:
    payload = _load_payload(Path(path) if path else None)
    defaults = dict(payload.get("defaults") or {})
    operations = payload.get("operations") or {}
    require(isinstance(operations, dict) and operations, "AI_OPERATION_ROUTE_INVALID", "Canonical operations are required.", 500)
    routes = {
        str(operation).upper(): _build_route(str(operation).upper(), dict(spec or {}), defaults)
        for operation, spec in operations.items()
    }
    aliases = {
        str(alias).upper(): str(canonical).upper()
        for alias, canonical in dict(payload.get("aliases") or {}).items()
    }
    for alias, canonical in aliases.items():
        require(canonical in routes, "AI_OPERATION_ROUTE_INVALID", f"Alias {alias} points to unknown {canonical}.", 500)
        require(alias not in routes, "AI_OPERATION_ROUTE_INVALID", f"Alias {alias} collides with a canonical operation.", 500)
    return routes, aliases, str(payload.get("version") or "1.0")


def canonical_operations() -> tuple[str, ...]:
    routes, _, _ = _registry()
    return tuple(sorted(routes))


def canonical_routes() -> dict[str, OperationRoute]:
    routes, _, _ = _registry()
    return dict(routes)


def operation_aliases() -> dict[str, str]:
    _, aliases, _ = _registry()
    return dict(aliases)


def resolve_operation(operation: str) -> str:
    key = str(operation or "").upper()
    routes, aliases, _ = _registry()
    canonical = aliases.get(key, key)
    if canonical not in routes:
        raise _undefined(key or "UNKNOWN")
    return canonical


def get_operation_route(operation: str) -> OperationRoute:
    routes, _, _ = _registry()
    canonical = resolve_operation(operation)
    spec = routes[canonical]
    requested = str(operation or "").upper()
    if requested == canonical:
        return spec
    return OperationRoute(
        operation=requested,
        base_capability_tier=spec.base_capability_tier,
        minimum_consequentiality=spec.minimum_consequentiality,
        reasoning_effort=spec.reasoning_effort,
        max_input_tokens=spec.max_input_tokens,
        max_output_tokens=spec.max_output_tokens,
        human_review_requirement=spec.human_review_requirement,
        capability=spec.capability,
    )


def required_tier_for_operation(operation: str) -> str:
    return get_operation_route(operation).base_capability_tier


def validate_routing_consistency(
    *,
    prompt_operations: Iterable[str],
    context_operations: Iterable[str] | None = None,
) -> None:
    canonical = set(canonical_operations())
    prompt_set = {str(item).upper() for item in prompt_operations}
    if prompt_set != canonical:
        missing = sorted(canonical - prompt_set)
        extra = sorted(prompt_set - canonical)
        raise DomainError(
            "ROUTING_REGISTRY_MISMATCH",
            "Prompt Registry operations do not match the canonical routing registry."
            + (f" Missing: {', '.join(missing)}." if missing else "")
            + (f" Extra: {', '.join(extra)}." if extra else ""),
            500,
        )
    if context_operations is None:
        return
    context_set = {str(item).upper() for item in context_operations}
    if context_set != canonical:
        missing = sorted(canonical - context_set)
        extra = sorted(context_set - canonical)
        raise DomainError(
            "ROUTING_REGISTRY_MISMATCH",
            "Context policy operations do not match the canonical routing registry."
            + (f" Missing: {', '.join(missing)}." if missing else "")
            + (f" Extra: {', '.join(extra)}." if extra else ""),
            500,
        )


# Compatibility alias used by PromptRegistry.get()
OPERATION_ALIASES = operation_aliases()

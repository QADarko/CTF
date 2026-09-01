from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from .errors import require
from .models import new_id, now_iso
from .operation_routes import canonical_routes, get_operation_route, required_tier_for_operation
from .repository import InMemoryRepository

__all__ = [
    "ROUTES",
    "AICostLedger",
    "ContextCompiler",
    "ModelRouter",
    "Route",
    "required_tier_for_operation",
    "route_public",
]


@dataclass(frozen=True, slots=True)
class Route:
    operation: str
    capability: str
    tier: str
    reasoning_effort: str
    max_input_tokens: int
    max_output_tokens: int
    allow_lower_capability_fallback: bool = False


def _route_from_spec(spec: Any, operation: str) -> Route:
    return Route(
        operation,
        spec.capability,
        spec.base_capability_tier,
        spec.reasoning_effort,
        spec.max_input_tokens,
        spec.max_output_tokens,
        False,
    )


ROUTES: dict[str, Route] = {
    operation: _route_from_spec(spec, operation) for operation, spec in canonical_routes().items()
}


class ModelRouter:
    def __init__(self, registry: Any | None = None) -> None:
        self.registry = registry

    def route(self, operation: str, consequentiality: str = "MEDIUM") -> Route:
        operation = operation.upper()
        route = _route_from_spec(get_operation_route(operation), operation)
        if consequentiality.upper() in {"HIGH", "CRITICAL"} and route.tier in {"T1", "T2"}:
            return Route(
                route.operation,
                "CRITICAL_REASONING",
                "T3",
                "HIGH",
                max(route.max_input_tokens, 16000),
                max(route.max_output_tokens, 1500),
                False,
            )
        return route

    def authorize(self, route: Route, *, provider: str, model: str, operation: str) -> None:
        if self.registry is None:
            return
        model_id = f"{provider}::{model}"
        self.registry.require_allowed(model_id, operation, route.tier, provider=provider, model=model)


class ContextCompiler:
    """Deprecated pass-through assembler. Prefer packages.ctf_domain.context_policy.ContextCompiler."""

    def compile(
        self,
        *,
        constitution: str,
        policy: str,
        authority_rules: str,
        memory: dict[str, Any],
        evidence: list[dict[str, Any]],
        user_input: str,
        schema: dict[str, Any],
        max_items: int = 50,
    ) -> dict[str, Any]:
        return {
            "constitution": constitution,
            "operation_policy": policy,
            "authority_rules": authority_rules,
            "confirmed_memory": memory,
            "relevant_evidence": evidence[:max_items],
            "current_user_input": user_input,
            "output_schema": schema,
        }


class AICostLedger:
    def __init__(self, repo: InMemoryRepository) -> None:
        self.repo = repo

    def record(
        self,
        *,
        project_id: str,
        operation: str,
        provider: str,
        model: str,
        capability: str,
        reasoning_effort: str,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        input_per_mtok: Decimal,
        cached_input_per_mtok: Decimal,
        output_per_mtok: Decimal,
        price_snapshot_id: str,
        latency_ms: int = 0,
    ) -> dict[str, Any]:
        require(input_tokens >= cached_input_tokens >= 0, "INVALID_INPUT", "Token usage is invalid.")
        require(output_tokens >= 0, "INVALID_INPUT", "Token usage is invalid.")
        uncached = input_tokens - cached_input_tokens
        cost = (
            Decimal(uncached) * input_per_mtok
            + Decimal(cached_input_tokens) * cached_input_per_mtok
            + Decimal(output_tokens) * output_per_mtok
        ) / Decimal(1_000_000)
        entry = {
            "id": new_id("air"),
            "project_id": project_id,
            "operation": operation.upper(),
            "provider": provider.upper(),
            "model": model,
            "capability": capability,
            "reasoning_effort": reasoning_effort.upper(),
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "price_snapshot_id": price_snapshot_id,
            "estimated_cost_usd": str(cost.quantize(Decimal("0.000001"))),
            "created_at": now_iso(),
        }
        self.repo.cost_entries.append(entry)
        self.repo.audit(project_id, "ai_usage_recorded", "SYSTEM", entry)
        return entry

    def summary(self, project_id: str) -> dict[str, Any]:
        rows = [row for row in self.repo.cost_entries if row["project_id"] == project_id]
        total = sum((Decimal(row["estimated_cost_usd"]) for row in rows), Decimal())
        by_operation: dict[str, Decimal] = {}
        for row in rows:
            by_operation[row["operation"]] = by_operation.get(row["operation"], Decimal()) + Decimal(
                row["estimated_cost_usd"]
            )
        return {
            "project_id": project_id,
            "runs": len(rows),
            "total_cost_usd": str(total),
            "by_operation": {key: str(value) for key, value in by_operation.items()},
            "entries": rows,
        }


def route_public(route: Route) -> dict[str, Any]:
    return asdict(route)

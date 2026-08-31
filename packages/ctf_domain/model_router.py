from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from .errors import DomainError, require
from .models import new_id, now_iso
from .repository import InMemoryRepository


@dataclass(frozen=True, slots=True)
class Route:
    operation: str
    capability: str
    tier: str
    reasoning_effort: str
    max_input_tokens: int
    max_output_tokens: int
    allow_lower_capability_fallback: bool = False


ROUTES: dict[str, Route] = {
    "CLASSIFICATION": Route("CLASSIFICATION", "EFFICIENT_AI", "T1", "NONE", 4000, 250),
    "CLAIM_EXTRACTION": Route("CLAIM_EXTRACTION", "EFFICIENT_AI", "T1", "LOW", 4000, 1000),
    "REALITY_UPDATE": Route("REALITY_UPDATE", "STANDARD_REASONING", "T2", "LOW", 8000, 2000),
    "QUESTION_REFRAME": Route("QUESTION_REFRAME", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1500),
    "PERCEPTION_SYNTHESIS": Route("PERCEPTION_SYNTHESIS", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 2000),
    "OPPORTUNITY_GENERATION": Route("OPPORTUNITY_GENERATION", "STANDARD_REASONING", "T2", "MEDIUM", 8000, 1000),
    "SPARK_GENERATION": Route("SPARK_GENERATION", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1200),
    "IDEA_BLUEPRINT": Route("IDEA_BLUEPRINT", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1500),
    "RED_TEAM": Route("RED_TEAM", "CRITICAL_REASONING", "T3", "HIGH", 24000, 2500),
    "DECISION_RECOMMENDATION": Route("DECISION_RECOMMENDATION", "CRITICAL_REASONING", "T3", "HIGH", 18000, 2200),
    "ROADMAP": Route("ROADMAP", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1800),
    "ROADMAP_REPLAN": Route("ROADMAP_REPLAN", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1500),
    "NBA": Route("NBA", "STANDARD_REASONING", "T2", "LOW", 8000, 600),
    "NEXT_BEST_ACTION": Route("NEXT_BEST_ACTION", "STANDARD_REASONING", "T2", "LOW", 8000, 600),
    "VALUE_ASSESSMENT": Route("VALUE_ASSESSMENT", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1800),
    "ATTRIBUTION": Route("ATTRIBUTION", "CRITICAL_REASONING", "T3", "HIGH", 24000, 2500),
    "TRANSFORMATION_ASSESSMENT": Route("TRANSFORMATION_ASSESSMENT", "CRITICAL_REASONING", "T3", "HIGH", 24000, 2500),
    "TRANSFORMATION": Route("TRANSFORMATION", "CRITICAL_REASONING", "T3", "HIGH", 24000, 1800),
    "REALIZED_VALUE": Route("REALIZED_VALUE", "STANDARD_REASONING", "T2", "MEDIUM", 16000, 1800),
    "R1_GENERATION": Route("R1_GENERATION", "CRITICAL_REASONING", "T3", "MEDIUM", 24000, 2000),
}


class ModelRouter:
    def route(self, operation: str, consequentiality: str = "MEDIUM") -> Route:
        operation = operation.upper()
        route = ROUTES.get(operation)
        if not route:
            raise DomainError("MODEL_ROUTE_NOT_FOUND", f"No model capability route for {operation}.", 404)
        if consequentiality.upper() == "CRITICAL" and route.tier in {"T1", "T2"}:
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

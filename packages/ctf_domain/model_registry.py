"""CTF Model Registry: exact Model × Operation × Tier route approvals."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import DomainError, require
from .model_router import required_tier_for_operation

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "evals" / "ctf_ai" / "registry" / "models.json"
STATUSES = ("CANDIDATE", "VALIDATED", "APPROVED", "BLOCKED", "DEPRECATED")
PRODUCTION_STATUSES = frozenset({"APPROVED"})
ROUTE_ERROR = "AI_MODEL_ROUTE_NOT_APPROVED"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def identity_key(provider: str, model: str, version: str | None = None) -> str:
    parts = [provider.upper(), model]
    if version:
        parts.append(version)
    return "::".join(parts)


def parse_model_id(model_id: str) -> tuple[str, str, str | None]:
    parts = [item for item in str(model_id).split("::") if item]
    if len(parts) >= 3:
        return parts[0], parts[1], "::".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], None
    return "", str(model_id), None


@dataclass(frozen=True, slots=True)
class ModelRouteApproval:
    operation: str
    tier: str

    def matches(self, operation: str, tier: str) -> bool:
        return self.operation == operation and self.tier == tier

    def as_dict(self) -> dict[str, str]:
        return {"operation": self.operation, "tier": self.tier}


def normalize_routes(record: dict[str, Any]) -> list[dict[str, str]]:
    """Migrate Cartesian lists into exact routes; never invent extra tier×operation pairs."""
    existing = record.get("approved_routes")
    if isinstance(existing, list) and existing:
        routes: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in existing:
            if not isinstance(item, dict):
                continue
            operation = str(item.get("operation") or "")
            tier = str(item.get("tier") or "")
            if not operation or not tier:
                continue
            key = (operation, tier)
            if key in seen:
                continue
            seen.add(key)
            routes.append({"operation": operation, "tier": tier})
        return routes
    operations = [str(item) for item in (record.get("approved_operations") or []) if item]
    blocked = {str(item) for item in (record.get("blocked_operations") or []) if item}
    routes = []
    for operation in operations:
        if operation in blocked:
            continue
        routes.append({"operation": operation, "tier": required_tier_for_operation(operation)})
    return routes


class ModelRegistry:
    def __init__(self, path: Path | None = None, *, enforced: bool | None = None) -> None:
        self.path = Path(path or os.getenv("CTF_MODEL_REGISTRY", DEFAULT_PATH))
        if enforced is None:
            enforced = os.getenv("CTF_ENFORCE_MODEL_REGISTRY", "").strip().lower() in {"1", "true", "yes"}
            if os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}:
                enforced = True
        self.enforced = enforced
        self.records: dict[str, dict[str, Any]] = {}
        self.load_error: str | None = None
        self._load()

    def is_available(self) -> bool:
        return self.path.is_file() and self.load_error is None

    def _load(self) -> None:
        if not self.path.is_file():
            self.load_error = "missing"
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.load_error = str(exc)
            return
        self.load_error = None
        for record in payload.get("models") or []:
            stored = dict(record)
            stored["approved_routes"] = normalize_routes(stored)
            key = identity_key(stored["provider"], stored["model"], stored.get("exact_version"))
            self.records[key] = stored

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"updated_at": _now(), "models": list(self.records.values())}, indent=2),
            encoding="utf-8",
        )
        self.load_error = None

    def get(self, provider: str, model: str, version: str | None = None) -> dict[str, Any] | None:
        if version:
            found = self.records.get(identity_key(provider, model, version))
            if found:
                return found
        found = self.records.get(identity_key(provider, model))
        if found:
            return found
        provider_key = provider.upper()
        for record in self.records.values():
            if str(record.get("provider", "")).upper() != provider_key:
                continue
            if str(record.get("model")) != model:
                continue
            if version and str(record.get("exact_version") or "") not in {version, model}:
                continue
            return record
        return None

    def get_by_id(self, model_id: str) -> dict[str, Any] | None:
        if model_id in self.records:
            return self.records[model_id]
        provider, model, version = parse_model_id(model_id)
        if provider and model:
            found = self.get(provider, model, version)
            if found:
                return found
        for record in self.records.values():
            if str(record.get("model")) == model_id:
                return record
        return None

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        status = str(record.get("status") or "CANDIDATE")
        require(status in STATUSES, "MODEL_REGISTRY_INVALID", f"Unknown model status {status}.", 400)
        stored = {
            "provider": str(record["provider"]),
            "model": str(record["model"]),
            "exact_version": record.get("exact_version") or record.get("model"),
            "approved_routes": normalize_routes(record),
            "approved_tiers": sorted({item["tier"] for item in normalize_routes(record)}),
            "approved_operations": [item["operation"] for item in normalize_routes(record)],
            "blocked_operations": list(record.get("blocked_operations") or []),
            "benchmark_version": str(record.get("benchmark_version") or "ctf-ai-golden-1"),
            "benchmark_score": record.get("benchmark_score"),
            "critical_safety_result": bool(record.get("critical_safety_result")),
            "human_review_status": str(record.get("human_review_status") or "PENDING"),
            "approval_date": record.get("approval_date"),
            "status": status,
            "updated_at": _now(),
        }
        self.records[identity_key(stored["provider"], stored["model"], stored["exact_version"])] = stored
        self.save()
        return stored

    def is_allowed(
        self,
        model_id: str | None = None,
        operation: str = "",
        tier: str = "",
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> bool:
        record = None
        if model_id:
            record = self.get_by_id(model_id)
        elif provider and model:
            record = self.get(provider, model)
        if not record:
            return False
        status = str(record.get("status") or "")
        if status == "CANDIDATE" or status not in {"APPROVED", "VALIDATED"}:
            return False
        if status == "VALIDATED" and tier == "T3":
            return False
        if operation in (record.get("blocked_operations") or []):
            return False
        routes = [ModelRouteApproval(item["operation"], item["tier"]) for item in normalize_routes(record)]
        return any(route.matches(operation, tier) for route in routes)

    def require_allowed(
        self,
        model_id: str | None = None,
        operation: str = "",
        tier: str = "",
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        if not self.enforced:
            return
        identity = model_id or identity_key(provider or "", model or "")
        if self.is_allowed(identity, operation, tier, provider=provider, model=model):
            return
        raise DomainError(
            ROUTE_ERROR,
            f"{identity} is not approved for {operation} at {tier}.",
            403,
        )


def record_from_report(report: dict[str, Any], *, status: str = "CANDIDATE") -> dict[str, Any]:
    approval = report.get("tier_approval") or {}
    cards = report.get("operation_scorecards") or []
    routes: list[dict[str, str]] = []
    for card in cards:
        if not card.get("approved"):
            continue
        operation = str(card.get("operation") or "")
        tier = str(card.get("required_tier") or required_tier_for_operation(operation))
        if tier == "T3":
            continue
        if approval.get(tier) != "APPROVED":
            continue
        routes.append({"operation": operation, "tier": tier})
    derived_status = status
    if approval.get("T1") != "APPROVED" and approval.get("T2") != "APPROVED":
        derived_status = "CANDIDATE"
    return {
        "provider": report.get("provider"),
        "model": report.get("model"),
        "exact_version": report.get("model"),
        "approved_routes": routes,
        "approved_tiers": sorted({item["tier"] for item in routes}),
        "approved_operations": [item["operation"] for item in routes],
        "blocked_operations": list(report.get("blocked_operations") or []),
        "benchmark_version": "ctf-ai-golden-1",
        "benchmark_score": report.get("overall_score"),
        "critical_safety_result": bool(report.get("critical_safety_pass")),
        "human_review_status": "PENDING" if approval.get("T3") == "PENDING_HUMAN_REVIEW" else "NOT_REQUIRED",
        "approval_date": None,
        "status": derived_status,
    }

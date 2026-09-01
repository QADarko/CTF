"""CTF Model Registry: Model × Operation × Tier approvals (CTF-MODEL-03)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import DomainError, require

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "evals" / "ctf_ai" / "registry" / "models.json"
STATUSES = ("CANDIDATE", "VALIDATED", "APPROVED", "BLOCKED", "DEPRECATED")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def identity_key(provider: str, model: str, version: str | None = None) -> str:
    parts = [provider.upper(), model]
    if version:
        parts.append(version)
    return "::".join(parts)


class ModelRegistry:
    def __init__(self, path: Path | None = None, *, enforced: bool | None = None) -> None:
        self.path = Path(path or os.getenv("CTF_MODEL_REGISTRY", DEFAULT_PATH))
        if enforced is None:
            enforced = os.getenv("CTF_ENFORCE_MODEL_REGISTRY", "").strip().lower() in {"1", "true", "yes"}
            if os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}:
                enforced = True
        self.enforced = enforced
        self.records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for record in payload.get("models") or []:
            key = identity_key(record["provider"], record["model"], record.get("exact_version"))
            self.records[key] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"updated_at": _now(), "models": list(self.records.values())}, indent=2),
            encoding="utf-8",
        )

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

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        status = str(record.get("status") or "CANDIDATE")
        require(status in STATUSES, "MODEL_REGISTRY_INVALID", f"Unknown model status {status}.", 400)
        stored = {
            "provider": str(record["provider"]),
            "model": str(record["model"]),
            "exact_version": record.get("exact_version") or record.get("model"),
            "approved_tiers": list(record.get("approved_tiers") or []),
            "approved_operations": list(record.get("approved_operations") or []),
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

    def is_allowed(self, *, provider: str, model: str, operation: str, tier: str) -> bool:
        record = self.get(provider, model)
        if not record or record.get("status") not in {"APPROVED", "VALIDATED"}:
            return False
        if record.get("status") == "VALIDATED" and tier == "T3":
            return False
        if tier not in (record.get("approved_tiers") or []):
            return False
        if operation in (record.get("blocked_operations") or []):
            return False
        approved_ops = record.get("approved_operations") or []
        return not approved_ops or operation in approved_ops

    def require_allowed(self, *, provider: str, model: str, operation: str, tier: str) -> None:
        if not self.enforced:
            return
        if self.is_allowed(provider=provider, model=model, operation=operation, tier=tier):
            return
        raise DomainError(
            "MODEL_NOT_APPROVED",
            f"{provider}/{model} is not approved for {operation} at {tier}.",
            403,
        )


def record_from_report(report: dict[str, Any], *, status: str = "CANDIDATE") -> dict[str, Any]:
    approval = report.get("tier_approval") or {}
    return {
        "provider": report.get("provider"),
        "model": report.get("model"),
        "exact_version": report.get("model"),
        "approved_tiers": [tier for tier in ("T1", "T2") if approval.get(tier) == "APPROVED"],
        "approved_operations": list(report.get("approved_operations") or []),
        "blocked_operations": list(report.get("blocked_operations") or []),
        "benchmark_version": "ctf-ai-golden-1",
        "benchmark_score": report.get("overall_score"),
        "critical_safety_result": bool(report.get("critical_safety_pass")),
        "human_review_status": "PENDING" if approval.get("T3") == "PENDING_HUMAN_REVIEW" else "NOT_REQUIRED",
        "approval_date": None,
        "status": status if approval.get("T1") == "APPROVED" or approval.get("T2") == "APPROVED" else "CANDIDATE",
    }

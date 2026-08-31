from __future__ import annotations

from collections import Counter
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from packages.ctf_domain.ai_runtime import AIExecutionService
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import SQLAlchemySnapshotRepository, repository


class CapabilityStatus(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    DEFERRED_V1 = "DEFERRED_V1"


class CapabilityPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CapabilityVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    OPERATOR = "OPERATOR"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    docs: list[str] = Field(default_factory=list)

    @field_validator("code", "tests", "docs")
    @classmethod
    def paths_are_relative(cls, paths: list[str]) -> list[str]:
        if any(Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
            raise ValueError("evidence paths must be repository-relative")
        return paths


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^CAP-[A-Z0-9]+-[0-9]{2}$")
    name: str = Field(min_length=3, max_length=120)
    area: str = Field(min_length=2, max_length=80)
    status: CapabilityStatus
    priority: CapabilityPriority
    architecture_refs: list[str] = Field(min_length=1)
    evidence: Evidence
    gaps: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    visibility: CapabilityVisibility
    last_verified: date

    @field_validator("gaps")
    @classmethod
    def implemented_has_no_gap(cls, gaps: list[str], info: Any) -> list[str]:
        if info.data.get("status") == CapabilityStatus.IMPLEMENTED and gaps:
            raise ValueError("implemented capabilities cannot declare gaps")
        return gaps


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^1\.[0-9]+$")
    generated_from: str
    last_verified: date
    capabilities: list[Capability] = Field(min_length=1)

    @field_validator("capabilities")
    @classmethod
    def ids_are_unique(cls, capabilities: list[Capability]) -> list[Capability]:
        ids = [capability.id for capability in capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("capability IDs must be unique")
        return capabilities


class ManifestState(BaseModel):
    manifest: CapabilityManifest | None = None
    error: str | None = None


MANIFEST_PATH = Path(__file__).resolve().parents[3] / "docs" / "capability-status.yaml"


def load_manifest(path: Path = MANIFEST_PATH) -> ManifestState:
    """Load and strictly validate status data without leaking paths or YAML details."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("manifest root is not an object")
        return ManifestState(manifest=CapabilityManifest.model_validate(raw))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, TypeError, ValueError):
        return ManifestState(error="Capability manifest is unavailable or invalid.")


router = APIRouter(prefix="/api/v1/system", tags=["System"])
ai_execution = AIExecutionService.from_env(repository)


def _state(request: Request) -> ManifestState:
    state = getattr(request.app.state, "capability_manifest", None)
    return state if isinstance(state, ManifestState) else load_manifest()


def _unavailable(state: ManifestState) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "CAPABILITY_MANIFEST_UNAVAILABLE",
                "message": state.error or "Capability manifest is unavailable.",
            }
        },
    )


@router.get("/capabilities", response_model=None)
def capabilities(
    request: Request,
    status: Annotated[list[CapabilityStatus] | None, Query()] = None,
    priority: Annotated[list[CapabilityPriority] | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    state = _state(request)
    if state.manifest is None:
        return _unavailable(state)
    all_capabilities = [
        capability
        for capability in state.manifest.capabilities
        if capability.visibility == CapabilityVisibility.PUBLIC
    ]
    filtered = [
        capability
        for capability in all_capabilities
        if (not status or capability.status in status)
        and (not priority or capability.priority in priority)
    ]
    status_counts = Counter(item.status.value for item in all_capabilities)
    priority_counts = Counter(item.priority.value for item in all_capabilities)
    return {
        "schema_version": state.manifest.schema_version,
        "last_verified": state.manifest.last_verified,
        "summary": {
            "total": len(all_capabilities),
            "matching": len(filtered),
            "by_status": {item.value: status_counts[item.value] for item in CapabilityStatus},
            "by_priority": {item.value: priority_counts[item.value] for item in CapabilityPriority},
        },
        "capabilities": [item.model_dump(mode="json") for item in filtered],
    }


def _capability(manifest: CapabilityManifest, capability_id: str) -> Capability | None:
    return next((item for item in manifest.capabilities if item.id == capability_id), None)


@router.get("/readiness", response_model=None)
def readiness(request: Request) -> dict[str, Any] | JSONResponse:
    state = _state(request)
    if state.manifest is None:
        return _unavailable(state)
    manifest = state.manifest
    public = [item for item in manifest.capabilities if item.visibility == CapabilityVisibility.PUBLIC]
    release_blockers = [
        {
            "id": item.id,
            "name": item.name,
            "status": item.status.value,
            "blocked_by": item.blocked_by,
            "gaps": item.gaps,
        }
        for item in public
        if item.priority == CapabilityPriority.P0
        and item.status != CapabilityStatus.IMPLEMENTED
    ]
    ai = ai_execution.readiness()
    worker = _capability(manifest, "CAP-DOC-03")
    khal = _capability(manifest, "CAP-ERI-02")
    pilot = _capability(manifest, "CAP-OPS-05")
    persistence = (
        "sqlalchemy-snapshot"
        if isinstance(repository, SQLAlchemySnapshotRepository)
        else "in-memory"
    )
    return {
        "last_verified": manifest.last_verified,
        "release": {
            "ready": not release_blockers,
            "blocker_count": len(release_blockers),
            "blockers": release_blockers,
        },
        "ai": {
            "provider": ai.get("provider", "NONE"),
            "configured": bool(ai.get("configured")),
            "reachable": bool(ai.get("reachable")),
            "ready": bool(ai.get("ready")),
            "non_production": bool(ai.get("non_production")),
            "allowed_tiers": ai.get("allowed_tiers", []),
            "limitations": ai.get("limitations", []),
        },
        "runtime": {
            "persistence": persistence,
            "durable": persistence != "in-memory",
            "object_store": object_store.backend,
            "object_store_durable": object_store.backend == "s3",
        },
        "document_worker": {
            "capability_id": worker.id if worker else None,
            "status": worker.status.value if worker else "UNKNOWN",
            "mode": "in-process-background-task",
            "limitations": worker.gaps if worker else ["Capability record unavailable."],
        },
        "khal": {
            "capability_id": khal.id if khal else None,
            "status": khal.status.value if khal else "UNKNOWN",
            "mode": "adapter-only",
            "limitations": khal.gaps if khal else ["Capability record unavailable."],
        },
        "pilot": {
            "capability_id": pilot.id if pilot else None,
            "status": pilot.status.value if pilot else "UNKNOWN",
            "completed": False,
            "limitations": pilot.gaps if pilot else ["Capability record unavailable."],
        },
    }

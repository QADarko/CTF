from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class AnonymousSession:
    id: str
    token: str
    tenant_id: str
    expires_at: str
    created_at: str

    @classmethod
    def create(cls, tenant_id: str = "public") -> AnonymousSession:
        return cls(
            id=new_id("ses"),
            token=new_id("tok"),
            tenant_id=tenant_id,
            expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
            created_at=now_iso(),
        )


@dataclass(slots=True)
class Gate:
    id: str
    number: int
    name: str
    status: str = "PENDING"
    decision: str | None = None
    decided_at: str | None = None
    actor_type: str | None = None


@dataclass(slots=True)
class Project:
    id: str
    tenant_id: str
    owner_session_id: str
    entry_family: str
    entry_type: str
    initial_input: str
    stage: str
    version: int
    methodology_version: str
    source: dict[str, Any]
    active_gate: Gate
    created_at: str
    updated_at: str
    memory: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["active_gate"] = asdict(self.active_gate)
        return data


@dataclass(slots=True)
class ResourceRecord:
    id: str
    project_id: str
    kind: str
    version: int
    data: dict[str, Any]
    status: str
    provenance: str
    immutable: bool
    created_at: str
    updated_at: str
    supersedes_id: str | None = None
    superseded_by: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditEvent:
    id: str
    project_id: str | None
    event_type: str
    actor_type: str
    data: dict[str, Any]
    occurred_at: str

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryVersion:
    id: str
    project_id: str
    version: int
    methodology_version: str
    data: dict[str, Any]
    operations: list[dict[str, Any]]
    created_at: str

    def public(self) -> dict[str, Any]:
        return asdict(self)

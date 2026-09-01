from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from .errors import DomainError, require
from .models import (
    AnonymousSession,
    AuditEvent,
    Gate,
    MemoryVersion,
    Project,
    ResourceRecord,
    new_id,
    now_iso,
)
from .state_machine import GATE_SPECS

INITIAL_MEMORY: dict[str, Any] = {
    "reality": {},
    "question": {},
    "perception": {},
    "claims": [],
    "evidence_ledger": [],
    "evidence_gaps": [],
    "opportunities": [],
    "sparks": [],
    "ideas": [],
    "assumptions": [],
    "decision_history": [],
    "commitments": [],
    "roadmaps": [],
    "creation_records": [],
    "value": {},
    "reality_snapshots": [],
    "creation_cycles": [],
    "document_provenance": [],
    "funding_context": {},
}


class InMemoryRepository:
    """Thread-safe repository with atomic rollback semantics for the alpha backend."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.sessions: dict[str, AnonymousSession] = {}
        self.session_tokens: dict[str, str] = {}
        self.projects: dict[str, Project] = {}
        self.resources: dict[str, ResourceRecord] = {}
        self.project_resources: dict[str, list[str]] = defaultdict(list)
        self.memory_versions: dict[str, list[MemoryVersion]] = defaultdict(list)
        self.audit_events: list[AuditEvent] = []
        self.creation_links: list[dict[str, Any]] = []
        self.idempotency: dict[tuple[str, str, str], Any] = {}
        self.external_event_keys: dict[tuple[str, str, str], str] = {}
        self.cost_entries: list[dict[str, Any]] = []
        self.ai_runs: list[dict[str, Any]] = []
        self.eri_connections: dict[str, dict[str, Any]] = {}
        self.metric_bindings: dict[str, dict[str, Any]] = {}
        self.security_counters: dict[str, Any] = {"rate": {}, "quota": {}}

    def _state_changed(self) -> None:
        """Persistence hook; in-memory repositories have nothing to flush."""

    def persist(self) -> None:
        """Flush direct aggregate mutations when no richer method is involved."""
        self._state_changed()

    def refresh(self) -> None:
        """Reload durable state. In-memory repositories are already current."""

    def persist_worker_delta(self) -> None:
        self.persist()

    def enable_worker_merge_mode(self) -> None:
        """In-memory repositories have a single writer; merge mode is a no-op."""

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            snapshot = deepcopy(
                (
                    self.sessions,
                    self.session_tokens,
                    self.projects,
                    self.resources,
                    self.project_resources,
                    self.memory_versions,
                    self.audit_events,
                    self.creation_links,
                    self.idempotency,
                    self.external_event_keys,
                    self.cost_entries,
                    self.ai_runs,
                    self.eri_connections,
                    self.metric_bindings,
                    self.security_counters,
                )
            )
            try:
                yield
            except Exception:
                (
                    self.sessions,
                    self.session_tokens,
                    self.projects,
                    self.resources,
                    self.project_resources,
                    self.memory_versions,
                    self.audit_events,
                    self.creation_links,
                    self.idempotency,
                    self.external_event_keys,
                    self.cost_entries,
                    self.ai_runs,
                    self.eri_connections,
                    self.metric_bindings,
                    self.security_counters,
                ) = snapshot
                raise

    def reset(self) -> None:
        with self._lock:
            self.__init__()

    def create_session(self, tenant_id: str = "public") -> AnonymousSession:
        with self._lock:
            session = AnonymousSession.create(tenant_id)
            self.sessions[session.id] = session
            self.session_tokens[session.token] = session.id
            self._state_changed()
            return deepcopy(session)

    def session_from_token(self, token: str | None) -> AnonymousSession:
        require(bool(token), "ACCESS_DENIED", "X-Session-Token is required.", 403)
        session_id = self.session_tokens.get(token or "")
        require(bool(session_id), "ACCESS_DENIED", "Session token is invalid.", 403)
        session = self.sessions[session_id or ""]
        expires_at = datetime.fromisoformat(session.expires_at)
        require(expires_at > datetime.now(UTC), "ACCESS_DENIED", "Session has expired.", 403)
        return deepcopy(session)

    def idempotent_get(self, scope: str, actor: str, key: str | None) -> Any | None:
        if not key:
            return None
        value = self.idempotency.get((scope, actor, key))
        return deepcopy(value)

    def idempotent_put(self, scope: str, actor: str, key: str | None, value: Any) -> None:
        if key:
            self.idempotency[(scope, actor, key)] = deepcopy(value)
            self._state_changed()

    def consume_rate_limit(
        self, identity: str, now: float, limit: int, window_seconds: int
    ) -> int:
        """Consume one request and return retry seconds, or zero when allowed."""
        with self._lock:
            bucket = self.security_counters["rate"].get(identity)
            if not bucket or now >= float(bucket["reset_at"]):
                bucket = {"count": 0, "reset_at": now + window_seconds}
            if int(bucket["count"]) >= limit:
                return max(1, int(float(bucket["reset_at"]) - now) + 1)
            bucket["count"] = int(bucket["count"]) + 1
            self.security_counters["rate"][identity] = bucket
            self._state_changed()
            return 0

    def reserve_ai_quota(
        self,
        tenant_id: str,
        day: str,
        tokens: int,
        cost_usd: str,
        token_limit: int,
        cost_limit_usd: str,
    ) -> None:
        from decimal import Decimal

        with self._lock:
            key = f"{tenant_id}:{day}"
            current = self.security_counters["quota"].get(
                key, {"tokens": 0, "cost_usd": "0"}
            )
            next_tokens = int(current["tokens"]) + tokens
            next_cost = Decimal(str(current["cost_usd"])) + Decimal(cost_usd)
            require(
                next_tokens <= token_limit and next_cost <= Decimal(cost_limit_usd),
                "AI_QUOTA_EXCEEDED",
                "Tenant AI token or cost quota is exhausted.",
                429,
            )
            self.security_counters["quota"][key] = {
                "tokens": next_tokens,
                "cost_usd": str(next_cost),
            }
            self._state_changed()

    def create_project(
        self,
        session: AnonymousSession,
        entry_family: str,
        entry_type: str,
        initial_input: str,
        source: dict[str, Any],
    ) -> Project:
        gate = Gate(new_id("gate"), 1, GATE_SPECS[1].name)
        project = Project(
            id=new_id("prj"),
            tenant_id=session.tenant_id,
            owner_session_id=session.id,
            entry_family=entry_family,
            entry_type=entry_type,
            initial_input=initial_input,
            stage="REALITY",
            version=1,
            methodology_version="CTF_FULL_V1",
            source=deepcopy(source),
            active_gate=gate,
            created_at=now_iso(),
            updated_at=now_iso(),
            memory=deepcopy(INITIAL_MEMORY),
        )
        self.projects[project.id] = project
        self.memory_versions[project.id].append(
            MemoryVersion(
                new_id("mem"),
                project.id,
                1,
                project.methodology_version,
                deepcopy(project.memory),
                [],
                now_iso(),
            )
        )
        self.audit(project.id, "project_created", "HUMAN", {"entry_family": entry_family})
        return deepcopy(project)

    def project_for(self, project_id: str, session: AnonymousSession) -> Project:
        project = self.projects.get(project_id)
        require(bool(project), "PROJECT_NOT_FOUND", "Project was not found.", 404)
        require(
            project.owner_session_id == session.id and project.tenant_id == session.tenant_id,
            "ACCESS_DENIED",
            "Project access is denied.",
            403,
        )
        return project

    def check_version(self, project: Project, expected_version: int | None) -> None:
        if expected_version is not None and project.version != expected_version:
            raise DomainError(
                "STATE_CONFLICT",
                f"Expected project version {expected_version}, current version is {project.version}.",
                409,
            )

    def touch(self, project: Project) -> None:
        project.version += 1
        project.updated_at = now_iso()
        self._state_changed()

    def audit(
        self,
        project_id: str | None,
        event_type: str,
        actor_type: str,
        data: dict[str, Any],
    ) -> AuditEvent:
        event = AuditEvent(new_id("aud"), project_id, event_type, actor_type, deepcopy(data), now_iso())
        self.audit_events.append(event)
        self._state_changed()
        return event

    def create_resource(
        self,
        project: Project,
        kind: str,
        data: dict[str, Any],
        *,
        status: str = "DRAFT",
        provenance: str = "USER",
        immutable: bool = False,
        resource_id: str | None = None,
    ) -> ResourceRecord:
        record = ResourceRecord(
            id=resource_id or new_id(kind[:4].lower()),
            project_id=project.id,
            kind=kind,
            version=1,
            data=deepcopy(data),
            status=status,
            provenance=provenance,
            immutable=immutable,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        self.resources[record.id] = record
        self.project_resources[project.id].append(record.id)
        self.audit(project.id, f"{kind.lower()}_created", provenance, {"resource_id": record.id})
        self.touch(project)
        return deepcopy(record)

    def list_resources(self, project: Project, kind: str) -> list[ResourceRecord]:
        return [
            deepcopy(self.resources[item_id])
            for item_id in self.project_resources[project.id]
            if self.resources[item_id].kind == kind
        ]

    def get_resource(self, project: Project, resource_id: str, kind: str | None = None) -> ResourceRecord:
        record = self.resources.get(resource_id)
        require(
            bool(record) and record.project_id == project.id and (kind is None or record.kind == kind),
            "RESOURCE_NOT_FOUND",
            "Resource was not found.",
            404,
        )
        return record

    def update_resource(
        self,
        project: Project,
        resource_id: str,
        patch: dict[str, Any],
        expected_version: int | None,
    ) -> ResourceRecord:
        record = self.get_resource(project, resource_id)
        require(
            not record.immutable,
            "IMMUTABLE_RECORD",
            "Confirmed record cannot be edited; create a superseding version.",
            409,
        )
        if expected_version is not None and record.version != expected_version:
            raise DomainError("STATE_CONFLICT", "Resource version is stale.", 409)
        record.data.update(deepcopy(patch))
        record.version += 1
        record.updated_at = now_iso()
        self.touch(project)
        self.audit(project.id, f"{record.kind.lower()}_updated", "HUMAN", {"resource_id": record.id})
        return deepcopy(record)

    def supersede_resource(
        self, project: Project, old_id: str, replacement_id: str
    ) -> ResourceRecord:
        old = self.get_resource(project, old_id)
        replacement = self.get_resource(project, replacement_id, old.kind)
        require(old.immutable, "SUPERSESSION_NOT_ALLOWED", "Only immutable records are superseded.")
        require(not old.superseded_by, "ALREADY_SUPERSEDED", "Record is already superseded.", 409)
        old.superseded_by = replacement.id
        old.updated_at = now_iso()
        replacement.supersedes_id = old.id
        self.add_link(project, old.kind, old.id, replacement.kind, replacement.id, "SUPERSEDES")
        self.audit(
            project.id,
            f"{old.kind.lower()}_superseded",
            "HUMAN",
            {"resource_id": old.id, "replacement_id": replacement.id},
        )
        self._state_changed()
        return deepcopy(replacement)

    def add_link(
        self,
        project: Project,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        relation: str,
    ) -> dict[str, Any]:
        for object_id in (from_id, to_id):
            record = self.resources.get(object_id)
            require(
                bool(record) and record.project_id == project.id,
                "INVALID_GENEALOGY_REFERENCE",
                f"Genealogy reference {object_id} is invalid.",
            )
        link = {
            "id": new_id("lnk"),
            "project_id": project.id,
            "from_type": from_type,
            "from_id": from_id,
            "to_type": to_type,
            "to_id": to_id,
            "relation": relation,
            "created_at": now_iso(),
        }
        self.creation_links.append(link)
        self.audit(project.id, "creation_link_created", "SYSTEM", link)
        return deepcopy(link)

    def project_audit(self, project: Project) -> list[dict[str, Any]]:
        return [e.public() for e in self.audit_events if e.project_id == project.id]

    def memory_history(self, project: Project) -> list[dict[str, Any]]:
        return [version.public() for version in self.memory_versions[project.id]]

    def snapshot_memory(
        self, project: Project, operations: list[dict[str, Any]]
    ) -> MemoryVersion:
        version = MemoryVersion(
            new_id("mem"),
            project.id,
            len(self.memory_versions[project.id]) + 1,
            project.methodology_version,
            deepcopy(project.memory),
            deepcopy(operations),
            now_iso(),
        )
        self.memory_versions[project.id].append(version)
        self._state_changed()
        return deepcopy(version)

    def dump(self) -> dict[str, Any]:
        return {
            "sessions": [asdict(v) for v in self.sessions.values()],
            "projects": [v.public() for v in self.projects.values()],
            "resources": [v.public() for v in self.resources.values()],
            "audit_events": [v.public() for v in self.audit_events],
        }


class SQLAlchemySnapshotRepository(InMemoryRepository):
    """Durable single-aggregate adapter preserving proven in-memory behavior.

    A transaction writes one JSON document atomically. This is intentionally a
    pragmatic modular-monolith adapter, not a multi-writer normalized store.
    """

    SNAPSHOT_ID = 1
    SCHEMA_VERSION = 1

    def __init__(self, database_url: str) -> None:
        super().__init__()
        from sqlalchemy import create_engine

        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self._database_url = database_url
        self._uses_postgres = "postgresql" in database_url
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.database_url = database_url
        self._engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
        self._transaction_depth = 0
        from .sqlalchemy_models import Base

        Base.metadata.create_all(self._engine)
        self._load()
        self._merge_on_flush = False
        self._worker_merge = False

    def enable_worker_merge_mode(self) -> None:
        """All subsequent flushes merge document deltas; never overwrite the API snapshot."""
        self._worker_merge = True

    def refresh(self) -> None:
        with self._lock:
            self._load()

    def persist_worker_delta(self) -> None:
        with self._lock:
            previous = self._merge_on_flush
            self._merge_on_flush = True
            try:
                self._flush_locked()
            finally:
                self._merge_on_flush = previous

    def _worker_safe(self) -> bool:
        return bool(self._worker_merge or self._merge_on_flush)

    def _payload(self) -> dict[str, Any]:
        payload = {
            "sessions": [asdict(item) for item in self.sessions.values()],
            "session_tokens": self.session_tokens,
            "projects": [asdict(item) for item in self.projects.values()],
            "resources": [asdict(item) for item in self.resources.values()],
            "project_resources": dict(self.project_resources),
            "memory_versions": {
                key: [asdict(item) for item in values]
                for key, values in self.memory_versions.items()
            },
            "audit_events": [asdict(item) for item in self.audit_events],
            "creation_links": self.creation_links,
            "idempotency": [
                {"scope": key[0], "actor": key[1], "key": key[2], "value": value}
                for key, value in self.idempotency.items()
            ],
            "external_event_keys": [
                {
                    "tenant_id": key[0],
                    "provider": key[1],
                    "external_event_id": key[2],
                    "resource_id": value,
                }
                for key, value in self.external_event_keys.items()
            ],
            "cost_entries": self.cost_entries,
            "ai_runs": self.ai_runs,
            "eri_connections": self.eri_connections,
            "metric_bindings": self.metric_bindings,
            "security_counters": self.security_counters,
        }
        return json.loads(
            json.dumps(
                payload,
                allow_nan=False,
                default=lambda value: value.isoformat()
                if isinstance(value, datetime)
                else str(value),
            )
        )

    def _restore(self, payload: dict[str, Any]) -> None:
        self.sessions = {
            item["id"]: AnonymousSession(**item) for item in payload.get("sessions", [])
        }
        self.session_tokens = dict(payload.get("session_tokens", {}))
        self.projects = {}
        for item in payload.get("projects", []):
            project_data = dict(item)
            project_data["active_gate"] = Gate(**project_data["active_gate"])
            project = Project(**project_data)
            self.projects[project.id] = project
        self.resources = {
            item["id"]: ResourceRecord(**item) for item in payload.get("resources", [])
        }
        self.project_resources = defaultdict(
            list,
            {
                key: list(values)
                for key, values in payload.get("project_resources", {}).items()
            },
        )
        self.memory_versions = defaultdict(
            list,
            {
                key: [MemoryVersion(**item) for item in values]
                for key, values in payload.get("memory_versions", {}).items()
            },
        )
        self.audit_events = [
            AuditEvent(**item) for item in payload.get("audit_events", [])
        ]
        self.creation_links = deepcopy(payload.get("creation_links", []))
        self.idempotency = {
            (item["scope"], item["actor"], item["key"]): deepcopy(item["value"])
            for item in payload.get("idempotency", [])
        }
        self.external_event_keys = {
            (item["tenant_id"], item["provider"], item["external_event_id"]): item[
                "resource_id"
            ]
            for item in payload.get("external_event_keys", [])
        }
        self.cost_entries = deepcopy(payload.get("cost_entries", []))
        self.ai_runs = deepcopy(payload.get("ai_runs", []))
        self.eri_connections = deepcopy(payload.get("eri_connections", {}))
        self.metric_bindings = deepcopy(payload.get("metric_bindings", {}))
        self.security_counters = deepcopy(
            payload.get("security_counters", {"rate": {}, "quota": {}})
        )

    def _load(self) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import RepositorySnapshotRow

        with Session(self._engine) as session:
            row = session.get(RepositorySnapshotRow, self.SNAPSHOT_ID)
            if row:
                self._restore(row.payload)

    def _flush_locked(self) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import RepositorySnapshotRow

        with Session(self._engine) as session:
            if getattr(self, "_uses_postgres", False):
                from sqlalchemy import text

                session.execute(text("SELECT pg_advisory_lock(:k)"), {"k": 871423})
            row = session.get(RepositorySnapshotRow, self.SNAPSHOT_ID)
            if row is None:
                row = RepositorySnapshotRow(
                    id=self.SNAPSHOT_ID,
                    schema_version=self.SCHEMA_VERSION,
                    payload=self._payload(),
                    updated_at=datetime.now(UTC),
                )
                session.add(row)
            else:
                incoming = self._payload()
                if self._worker_safe():
                    conflicts = worker_version_conflicts(row.payload, incoming)
                    if conflicts:
                        raise DomainError(
                            "WORKER_VERSION_CONFLICT",
                            "Worker document state is stale relative to the latest snapshot.",
                            409,
                        )
                    incoming = merge_worker_snapshot(row.payload, incoming)
                    self._restore(incoming)
                row.schema_version = self.SCHEMA_VERSION
                row.payload = incoming
                row.updated_at = datetime.now(UTC)
            session.commit()
            if getattr(self, "_uses_postgres", False):
                from sqlalchemy import text

                session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": 871423})
                session.commit()

    def _state_changed(self) -> None:
        if self._transaction_depth == 0:
            with self._lock:
                self._flush_locked()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            snapshot = None if self._worker_safe() else deepcopy(self._payload())
            previous_merge = self._merge_on_flush
            if self._worker_merge:
                self._merge_on_flush = True
            self._transaction_depth += 1
            try:
                yield
                if self._transaction_depth == 1:
                    self._flush_locked()
            except Exception:
                if snapshot is None:
                    self._load()
                else:
                    self._restore(snapshot)
                raise
            finally:
                self._transaction_depth -= 1
                self._merge_on_flush = previous_merge

    def reset(self) -> None:
        with self._lock:
            self._restore({})
            self._flush_locked()

    def close(self) -> None:
        self._engine.dispose()


WORKER_DELTA_KINDS = frozenset(
    {
        "DOCUMENT_JOB",
        "ATTACHMENT",
        "EVIDENCE_SOURCE",
        "PARSED_DOCUMENT",
        "DOCUMENT_CHUNK",
        "CLAIM",
        "EVIDENCE",
    }
)


def merge_worker_snapshot(latest: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Keep API state and overlay only document-processing entities from the worker."""
    merged = deepcopy(latest or {})
    latest_resources = {item["id"]: item for item in merged.get("resources", [])}
    incoming_resources = {item["id"]: item for item in incoming.get("resources", [])}
    for resource_id, record in incoming_resources.items():
        if record.get("kind") in WORKER_DELTA_KINDS:
            latest_resources[resource_id] = record
    merged["resources"] = list(latest_resources.values())
    project_resources = dict(merged.get("project_resources") or {})
    for project_id, ids in (incoming.get("project_resources") or {}).items():
        existing = list(project_resources.get(project_id) or [])
        for resource_id in ids:
            if resource_id not in existing:
                existing.append(resource_id)
        project_resources[project_id] = existing
    merged["project_resources"] = project_resources
    seen_audit = {item.get("id") for item in merged.get("audit_events") or []}
    audits = list(merged.get("audit_events") or [])
    for event in incoming.get("audit_events") or []:
        if event.get("id") not in seen_audit:
            audits.append(event)
            seen_audit.add(event.get("id"))
    merged["audit_events"] = audits
    latest_projects = {item["id"]: item for item in merged.get("projects") or []}
    incoming_projects = {item["id"]: item for item in incoming.get("projects") or []}
    for project_id, project in incoming_projects.items():
        if project_id not in latest_projects:
            latest_projects[project_id] = project
            continue
        current = latest_projects[project_id]
        incoming_memory = project.get("memory") or {}
        current_memory = current.setdefault("memory", {})
        for key in ("claims", "evidence_ledger", "evidence_gaps", "document_provenance"):
            if key not in incoming_memory:
                continue
            existing = list(current_memory.get(key) or [])
            seen = {item.get("id") for item in existing if isinstance(item, dict)}
            for item in incoming_memory.get(key) or []:
                if isinstance(item, dict) and item.get("id") not in seen:
                    existing.append(item)
                    seen.add(item.get("id"))
            current_memory[key] = existing
    merged["projects"] = list(latest_projects.values())
    seen_links = {item.get("id") for item in merged.get("creation_links") or []}
    links = list(merged.get("creation_links") or [])
    for link in incoming.get("creation_links") or []:
        if link.get("id") not in seen_links:
            links.append(link)
            seen_links.add(link.get("id"))
    merged["creation_links"] = links
    latest_memory = dict(merged.get("memory_versions") or {})
    for project_id, versions in (incoming.get("memory_versions") or {}).items():
        existing = list(latest_memory.get(project_id) or [])
        seen = {item.get("id") for item in existing if isinstance(item, dict)}
        for item in versions or []:
            if isinstance(item, dict) and item.get("id") not in seen:
                existing.append(item)
                seen.add(item.get("id"))
        latest_memory[project_id] = existing
    merged["memory_versions"] = latest_memory
    return merged


def worker_version_conflicts(latest: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
    """Detect stale worker copies of document entities that would clobber a newer write."""
    latest_resources = {item["id"]: item for item in latest.get("resources") or []}
    conflicts: list[str] = []
    for record in incoming.get("resources") or []:
        if record.get("kind") not in WORKER_DELTA_KINDS:
            continue
        current = latest_resources.get(record["id"])
        if current is None:
            continue
        if int(current.get("version") or 0) > int(record.get("version") or 0):
            conflicts.append(record["id"])
    return conflicts


def create_repository(database_url: str | None = None) -> InMemoryRepository:
    selected = database_url if database_url is not None else os.getenv("CTF_DATABASE_URL", "")
    if not selected or selected.lower() in {"memory", "in-memory"}:
        return InMemoryRepository()
    return SQLAlchemySnapshotRepository(selected)


repository = create_repository()

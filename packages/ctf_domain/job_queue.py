"""Durable document job queue with a local in-process fallback (CTF-012)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .errors import DomainError
from .models import now_iso
from .repository import InMemoryRepository

JOB_STATES = (
    "QUEUED",
    "CLAIMED",
    "PROCESSING",
    "RETRY_WAIT",
    "COMPLETED",
    "FAILED",
    "DEAD_LETTER",
)
TRANSIENT_CODES = {"OBJECT_STORE_FAILURE", "WORKER_CRASH", "TIMEOUT", "TEMPORARY_FAILURE", "DOCUMENT_UNAVAILABLE", "WORKER_VERSION_CONFLICT"}
TERMINAL_CODES = {
    "INVALID_DOCUMENT",
    "MALWARE_DETECTED",
    "UNSUPPORTED_DOCUMENT",
    "UNSAFE_DOCUMENT",
    "ARCHIVE_BOMB",
    "DOCUMENT_LIMIT_EXCEEDED",
    "CHECKSUM_MISMATCH",
}


@dataclass
class DocumentJob:
    project_id: str
    job_id: str
    attempt: int = 1
    max_attempts: int = 3
    claimed_at: str | None = None
    lease_expires_at: str | None = None
    last_error: str | None = None
    state: str = "QUEUED"
    extra: dict[str, Any] = field(default_factory=dict)


class DocumentJobQueue(Protocol):
    durable: bool

    def enqueue(self, *, project_id: str, job_id: str, attachment_id: str | None = None) -> None: ...
    def claim(self, worker_id: str | None = None) -> DocumentJob | None: ...
    def renew_lease(self, job_id: str, worker_id: str | None = None) -> None: ...
    def complete(self, job_id: str) -> None: ...
    def retry(self, job_id: str, reason: str) -> None: ...
    def fail(self, job_id: str, code: str) -> None: ...


class InProcessDocumentJobQueue:
    durable = False

    def __init__(self, repository: InMemoryRepository, lease_seconds: int = 60) -> None:
        self.repository = repository
        self.lease_seconds = lease_seconds

    def enqueue(self, *, project_id: str, job_id: str, attachment_id: str | None = None) -> None:
        del attachment_id
        self._update(project_id, job_id, state="QUEUED", attempt=1)

    def renew_lease(self, job_id: str, worker_id: str | None = None) -> None:
        del worker_id
        record, _ = self._find(job_id)
        meta = record.data.setdefault("queue", {})
        expires = (datetime.now(UTC) + timedelta(seconds=self.lease_seconds)).isoformat()
        meta["lease_expires_at"] = expires
        record.data["queue"] = meta

    def claim(self, worker_id: str | None = None) -> DocumentJob | None:
        del worker_id
        now = datetime.now(UTC)
        for project in self.repository.projects.values():
            for listed in self.repository.list_resources(project, "DOCUMENT_JOB"):
                record = self.repository.get_resource(project, listed.id, "DOCUMENT_JOB")
                meta = record.data.setdefault("queue", {})
                state = meta.get("state", record.status)
                lease = meta.get("lease_expires_at")
                expired = bool(lease and datetime.fromisoformat(lease) <= now)
                if state in {"QUEUED", "RETRY_WAIT"} or (state == "CLAIMED" and expired):
                    if state == "CLAIMED" and expired:
                        meta["last_error"] = "DOCUMENT_JOB_LEASE_EXPIRED"
                    claimed_at = now_iso()
                    expires = (now + timedelta(seconds=self.lease_seconds)).isoformat()
                    meta.update(
                        {
                            "state": "CLAIMED",
                            "claimed_at": claimed_at,
                            "lease_expires_at": expires,
                            "attempt": int(meta.get("attempt") or 1),
                            "max_attempts": int(meta.get("max_attempts") or 3),
                        }
                    )
                    record.status = "CLAIMED"
                    record.data["status"] = "CLAIMED"
                    return DocumentJob(
                        project_id=project.id,
                        job_id=record.id,
                        attempt=int(meta["attempt"]),
                        max_attempts=int(meta["max_attempts"]),
                        claimed_at=claimed_at,
                        lease_expires_at=expires,
                        last_error=meta.get("last_error"),
                        state="CLAIMED",
                    )
        return None

    def complete(self, job_id: str) -> None:
        record, _ = self._find(job_id)
        if record.status == "COMPLETED":
            return
        record.data.setdefault("queue", {})["state"] = "COMPLETED"
        record.status = "COMPLETED"
        record.data["status"] = "COMPLETED"

    def retry(self, job_id: str, reason: str) -> None:
        record, _ = self._find(job_id)
        meta = record.data.setdefault("queue", {})
        attempt = int(meta.get("attempt") or 1) + 1
        max_attempts = int(meta.get("max_attempts") or 3)
        meta["last_error"] = reason
        meta["attempt"] = attempt
        if attempt > max_attempts or reason in TERMINAL_CODES:
            self.fail(job_id, "DOCUMENT_JOB_RETRY_EXHAUSTED" if attempt > max_attempts else reason)
            return
        meta["state"] = "RETRY_WAIT"
        record.status = "RETRY_WAIT"
        record.data["status"] = "RETRY_WAIT"

    def fail(self, job_id: str, code: str) -> None:
        record, _ = self._find(job_id)
        meta = record.data.setdefault("queue", {})
        meta["state"] = "DEAD_LETTER" if code == "DOCUMENT_JOB_RETRY_EXHAUSTED" else "FAILED"
        meta["last_error"] = code
        record.status = meta["state"]
        record.data["status"] = meta["state"]
        record.data["error"] = {"code": code}

    def _find(self, job_id: str):
        for project in self.repository.projects.values():
            try:
                return self.repository.get_resource(project, job_id, "DOCUMENT_JOB"), project
            except DomainError:
                continue
        raise DomainError("RESOURCE_NOT_FOUND", "Document job was not found.", 404)

    def _update(self, project_id: str, job_id: str, **fields: Any) -> None:
        project = self.repository.projects[project_id]
        record = self.repository.get_resource(project, job_id, "DOCUMENT_JOB")
        meta = record.data.setdefault("queue", {})
        meta.setdefault("max_attempts", 3)
        meta.setdefault("attempt", 1)
        meta.update(fields)
        record.data["status"] = meta.get("state", record.status)


class PostgresDocumentJobQueue:
    durable = True

    def __init__(self, database_url: str, lease_seconds: int = 60) -> None:
        from sqlalchemy import create_engine

        from .sqlalchemy_models import Base, DocumentJobRow

        if "postgres" not in database_url.lower():
            raise DomainError(
                "DOCUMENT_QUEUE_NOT_DURABLE",
                "Durable document queue requires a PostgreSQL URL.",
                503,
            )
        self.database_url = database_url
        self.lease_seconds = lease_seconds
        self._engine = create_engine(database_url, pool_pre_ping=True)
        DocumentJobRow.__table__.create(self._engine, checkfirst=True)
        Base.metadata.create_all(self._engine, tables=[DocumentJobRow.__table__], checkfirst=True)

    def enqueue(self, *, project_id: str, job_id: str, attachment_id: str | None = None) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import DocumentJobRow

        now = datetime.now(UTC)
        with Session(self._engine) as session:
            row = session.get(DocumentJobRow, job_id)
            if row is None:
                session.add(
                    DocumentJobRow(
                        id=job_id,
                        project_id=project_id,
                        attachment_id=attachment_id,
                        status="QUEUED",
                        attempt=1,
                        max_attempts=3,
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif row.status in {"COMPLETED", "FAILED", "DEAD_LETTER"}:
                return
            else:
                row.status = "QUEUED"
                row.available_at = now
                row.updated_at = now
            session.commit()

    def claim(self, worker_id: str | None = None) -> DocumentJob | None:
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import DocumentJobRow

        worker = worker_id or f"worker_{os.getpid()}"
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self.lease_seconds)
        with Session(self._engine) as session:
            selected = session.execute(
                text(
                    """
                    SELECT id FROM document_jobs
                    WHERE available_at <= :now
                      AND (
                        status IN ('QUEUED', 'RETRY_WAIT')
                        OR (status = 'CLAIMED' AND lease_expires_at IS NOT NULL AND lease_expires_at < :now)
                      )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                ),
                {"now": now},
            ).first()
            if selected is None:
                return None
            row = session.get(DocumentJobRow, selected[0])
            if row is None:
                return None
            if row.status == "CLAIMED" and row.lease_expires_at and row.lease_expires_at < now:
                row.last_error = "DOCUMENT_JOB_LEASE_EXPIRED"
            row.status = "CLAIMED"
            row.claimed_at = now
            row.lease_expires_at = expires
            row.claimed_by = worker
            row.updated_at = now
            session.commit()
            return DocumentJob(
                project_id=row.project_id,
                job_id=row.id,
                attempt=row.attempt,
                max_attempts=row.max_attempts,
                claimed_at=row.claimed_at.isoformat() if row.claimed_at else None,
                lease_expires_at=row.lease_expires_at.isoformat() if row.lease_expires_at else None,
                last_error=row.last_error,
                state="CLAIMED",
                extra={"attachment_id": row.attachment_id, "claimed_by": worker},
            )

    def renew_lease(self, job_id: str, worker_id: str | None = None) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import DocumentJobRow

        with Session(self._engine) as session:
            row = session.get(DocumentJobRow, job_id)
            if row is None or row.status != "CLAIMED":
                return
            if worker_id and row.claimed_by and row.claimed_by != worker_id:
                return
            row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
            row.updated_at = datetime.now(UTC)
            session.commit()

    def complete(self, job_id: str) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import DocumentJobRow

        with Session(self._engine) as session:
            row = session.get(DocumentJobRow, job_id)
            if row is None or row.status == "COMPLETED":
                return
            row.status = "COMPLETED"
            row.updated_at = datetime.now(UTC)
            session.commit()

    def retry(self, job_id: str, reason: str) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import DocumentJobRow

        with Session(self._engine) as session:
            row = session.get(DocumentJobRow, job_id)
            if row is None:
                raise DomainError("RESOURCE_NOT_FOUND", "Document job was not found.", 404)
            row.attempt += 1
            row.last_error = reason
            row.updated_at = datetime.now(UTC)
            if row.attempt > row.max_attempts or reason in TERMINAL_CODES:
                row.status = "DEAD_LETTER" if row.attempt > row.max_attempts else "FAILED"
                session.commit()
                return
            row.status = "RETRY_WAIT"
            row.available_at = datetime.now(UTC)
            row.claimed_at = None
            row.lease_expires_at = None
            row.claimed_by = None
            session.commit()

    def fail(self, job_id: str, code: str) -> None:
        from sqlalchemy.orm import Session

        from .sqlalchemy_models import DocumentJobRow

        with Session(self._engine) as session:
            row = session.get(DocumentJobRow, job_id)
            if row is None:
                raise DomainError("RESOURCE_NOT_FOUND", "Document job was not found.", 404)
            row.status = "DEAD_LETTER" if code == "DOCUMENT_JOB_RETRY_EXHAUSTED" else "FAILED"
            row.last_error = code
            row.updated_at = datetime.now(UTC)
            session.commit()

    def close(self) -> None:
        self._engine.dispose()


def create_document_job_queue(
    repository: InMemoryRepository,
    database_url: str | None = None,
) -> DocumentJobQueue:
    selection = os.getenv("CTF_DOCUMENT_QUEUE", "in-process").strip().lower()
    url = database_url or os.getenv("CTF_DOCUMENT_QUEUE_URL") or os.getenv("CTF_DATABASE_URL", "")
    production = os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}
    wants_durable = selection in {"durable", "postgres"}
    if production and not wants_durable:
        raise DomainError(
            "DOCUMENT_QUEUE_NOT_DURABLE",
            "Production refuses the in-process document queue. Set CTF_DOCUMENT_QUEUE=postgres.",
            503,
        )
    if wants_durable or (selection != "in-process" and "postgres" in url.lower()):
        if "postgres" not in url.lower():
            if os.getenv("APP_ENV", "").lower() == "production":
                raise DomainError(
                    "DOCUMENT_QUEUE_NOT_DURABLE",
                    "Production durable document queue requires PostgreSQL.",
                    503,
                )
            return InProcessDocumentJobQueue(repository)
        return PostgresDocumentJobQueue(url)
    return InProcessDocumentJobQueue(repository)

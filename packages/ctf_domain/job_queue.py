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
TRANSIENT_CODES = {"OBJECT_STORE_FAILURE", "WORKER_CRASH", "TIMEOUT", "TEMPORARY_FAILURE"}
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

    def enqueue(self, *, project_id: str, job_id: str) -> None: ...
    def claim(self) -> DocumentJob | None: ...
    def complete(self, job_id: str) -> None: ...
    def retry(self, job_id: str, reason: str) -> None: ...
    def fail(self, job_id: str, code: str) -> None: ...


class InProcessDocumentJobQueue:
    durable = False

    def __init__(self, repository: InMemoryRepository, lease_seconds: int = 60) -> None:
        self.repository = repository
        self.lease_seconds = lease_seconds

    def enqueue(self, *, project_id: str, job_id: str) -> None:
        self._update(project_id, job_id, state="QUEUED", attempt=1)

    def claim(self) -> DocumentJob | None:
        now = datetime.now(UTC)
        for project in self.repository.projects.values():
            for record in self.repository.list_resources(project, "DOCUMENT_JOB"):
                meta = record.data.setdefault("queue", {})
                state = meta.get("state", record.status)
                lease = meta.get("lease_expires_at")
                expired = bool(lease and datetime.fromisoformat(lease) < now)
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


def create_document_job_queue(repository: InMemoryRepository) -> DocumentJobQueue:
    selection = os.getenv("CTF_DOCUMENT_QUEUE", "in-process").strip().lower()
    queue = InProcessDocumentJobQueue(repository)
    if selection in {"durable", "snapshot", "postgres"}:
        queue.durable = True  # type: ignore[misc]
    return queue

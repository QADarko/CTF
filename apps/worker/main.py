"""Claim DOCUMENT_JOB records and process them outside the API request cycle."""

from __future__ import annotations

import os
import threading
import time

from packages.ctf_domain.document_intelligence import (
    PERMANENT_FAILURE,
    RETRYABLE_FAILURE,
    DocumentIntelligenceService,
    DocumentProcessingError,
)
from packages.ctf_domain.job_queue import TRANSIENT_CODES, create_document_job_queue
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import repository


def _heartbeat(queue, job_id: str, worker_id: str, stop: threading.Event, interval: float) -> None:
    while not stop.wait(interval):
        queue.renew_lease(job_id, worker_id)


def run_once(queue=None, intelligence=None, *, worker_id: str | None = None, heartbeat_seconds: float | None = None) -> bool:
    repo = getattr(intelligence, "repository", None) or repository
    if hasattr(repo, "refresh"):
        repo.refresh()
    queue = queue or create_document_job_queue(repo)
    intelligence = intelligence or DocumentIntelligenceService(repo, object_store)
    worker = worker_id or f"worker_{os.getpid()}"
    job = queue.claim(worker)
    if job is None:
        return False
    stop = threading.Event()
    interval = float(heartbeat_seconds or max(1.0, getattr(queue, "lease_seconds", 60) / 3))
    beat = threading.Thread(target=_heartbeat, args=(queue, job.job_id, worker, stop, interval), daemon=True)
    beat.start()
    try:
        if hasattr(repo, "refresh"):
            repo.refresh()
        result = intelligence.process(job.project_id, job.job_id)
        if hasattr(repo, "persist_worker_delta"):
            repo.persist_worker_delta()
        if result.ok:
            queue.complete(job.job_id)
        elif result.status == RETRYABLE_FAILURE or (result.code or "") in TRANSIENT_CODES:
            queue.retry(job.job_id, result.code or "TEMPORARY_FAILURE")
        elif result.status == PERMANENT_FAILURE:
            queue.fail(job.job_id, result.code or "DOCUMENT_PROCESSING_FAILED")
        else:
            queue.fail(job.job_id, result.code or "DOCUMENT_PROCESSING_FAILED")
    except DocumentProcessingError as exc:
        if exc.code in TRANSIENT_CODES:
            queue.retry(job.job_id, exc.code)
        else:
            queue.fail(job.job_id, exc.code)
    except Exception:  # noqa: BLE001 - worker must reclaim the lease after any crash
        queue.retry(job.job_id, "WORKER_CRASH")
    finally:
        stop.set()
    return True


def main() -> None:
    interval = float(os.getenv("CTF_WORKER_POLL_SECONDS", "2"))
    while True:
        if not run_once():
            time.sleep(interval)


if __name__ == "__main__":
    main()

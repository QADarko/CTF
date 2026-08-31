"""Claim DOCUMENT_JOB records and process them outside the API request cycle."""

from __future__ import annotations

import os
import time

from packages.ctf_domain.document_intelligence import (
    DocumentIntelligenceService,
    DocumentProcessingError,
)
from packages.ctf_domain.job_queue import TRANSIENT_CODES, create_document_job_queue
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import repository


def run_once(queue=None, intelligence=None) -> bool:
    queue = queue or create_document_job_queue(repository)
    intelligence = intelligence or DocumentIntelligenceService(repository, object_store)
    job = queue.claim()
    if job is None:
        return False
    try:
        queue.renew_lease(job.job_id)
        intelligence.process(job.project_id, job.job_id)
        queue.complete(job.job_id)
    except DocumentProcessingError as exc:
        if exc.code in TRANSIENT_CODES:
            queue.retry(job.job_id, exc.code)
        else:
            queue.fail(job.job_id, exc.code)
    except Exception:  # noqa: BLE001 - worker must reclaim the lease after any crash
        queue.retry(job.job_id, "WORKER_CRASH")
    return True


def main() -> None:
    interval = float(os.getenv("CTF_WORKER_POLL_SECONDS", "2"))
    while True:
        if not run_once():
            time.sleep(interval)


if __name__ == "__main__":
    main()

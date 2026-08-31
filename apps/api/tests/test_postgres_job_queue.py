from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from packages.ctf_domain.job_queue import PostgresDocumentJobQueue


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"

pytestmark = pytest.mark.skipif(
    not os.getenv("CTF_TEST_POSTGRES_URL"),
    reason="Set CTF_TEST_POSTGRES_URL to run PostgreSQL document queue tests.",
)


@pytest.fixture
def queue():
    instance = PostgresDocumentJobQueue(os.environ["CTF_TEST_POSTGRES_URL"], lease_seconds=2)
    yield instance
    instance.close()


def test_postgres_job_survives_api_restart(queue):
    job_id = _id("job_restart")
    queue.enqueue(project_id="prj_a", job_id=job_id)
    queue.close()
    restarted = PostgresDocumentJobQueue(os.environ["CTF_TEST_POSTGRES_URL"], lease_seconds=2)
    claimed = restarted.claim(worker_id="worker-b")
    assert claimed is not None
    assert claimed.job_id == job_id
    restarted.close()


def test_worker_process_can_claim_api_created_job(queue):
    api_queue = PostgresDocumentJobQueue(os.environ["CTF_TEST_POSTGRES_URL"])
    job_id = _id("job_cross")
    api_queue.enqueue(project_id="prj_b", job_id=job_id)
    api_queue.close()
    claimed = queue.claim(worker_id="worker-c")
    assert claimed is not None
    assert claimed.job_id == job_id


def test_two_workers_do_not_claim_same_job(queue):
    job_id = _id("job_race")
    queue.enqueue(project_id="prj_c", job_id=job_id)

    def claim_one(worker: str):
        other = PostgresDocumentJobQueue(os.environ["CTF_TEST_POSTGRES_URL"])
        try:
            return other.claim(worker_id=worker)
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(claim_one, "w1")
        second = pool.submit(claim_one, "w2")
        results = [first.result(), second.result()]
    claimed = [item.job_id for item in results if item is not None]
    assert len(claimed) == len(set(claimed))


def test_expired_lease_can_be_reclaimed(queue):
    job_id = _id("job_lease")
    queue.enqueue(project_id="prj_d", job_id=job_id)
    first = queue.claim(worker_id="slow")
    assert first is not None
    from sqlalchemy.orm import Session

    from packages.ctf_domain.sqlalchemy_models import DocumentJobRow

    with Session(queue._engine) as session:
        row = session.get(DocumentJobRow, job_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    reclaimed = queue.claim(worker_id="fast")
    assert reclaimed is not None
    assert reclaimed.job_id == job_id


def test_completed_job_is_not_reprocessed(queue):
    job_id = _id("job_done")
    queue.enqueue(project_id="prj_e", job_id=job_id)
    claimed = queue.claim()
    assert claimed is not None
    queue.complete(job_id)
    queue.complete(job_id)
    again = queue.claim()
    assert again is None or again.job_id != job_id


def test_transient_failure_retries(queue):
    job_id = _id("job_retry")
    queue.enqueue(project_id="prj_f", job_id=job_id)
    queue.retry(job_id, "OBJECT_STORE_FAILURE")
    claimed = queue.claim()
    assert claimed is not None
    assert claimed.job_id == job_id


def test_retry_limit_enters_dead_letter(queue):
    job_id = _id("job_dead")
    queue.enqueue(project_id="prj_g", job_id=job_id)
    queue.retry(job_id, "WORKER_CRASH")
    queue.retry(job_id, "WORKER_CRASH")
    queue.retry(job_id, "WORKER_CRASH")
    from sqlalchemy.orm import Session

    from packages.ctf_domain.sqlalchemy_models import DocumentJobRow

    with Session(queue._engine) as session:
        assert session.get(DocumentJobRow, job_id).status == "DEAD_LETTER"


def test_invalid_document_is_not_retried_forever(queue):
    job_id = _id("job_bad")
    queue.enqueue(project_id="prj_h", job_id=job_id)
    queue.retry(job_id, "INVALID_DOCUMENT")
    from sqlalchemy.orm import Session

    from packages.ctf_domain.sqlalchemy_models import DocumentJobRow

    with Session(queue._engine) as session:
        assert session.get(DocumentJobRow, job_id).status == "FAILED"

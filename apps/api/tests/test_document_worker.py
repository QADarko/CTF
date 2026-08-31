from __future__ import annotations

from packages.ctf_domain.job_queue import InProcessDocumentJobQueue
from packages.ctf_domain.repository import InMemoryRepository


def _job(repo: InMemoryRepository):
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    job = repo.create_resource(project, "DOCUMENT_JOB", {"status": "QUEUED"}, status="QUEUED")
    return project, job


def test_job_survives_api_restart_metadata():
    repo = InMemoryRepository()
    project, job = _job(repo)
    queue = InProcessDocumentJobQueue(repo)
    queue.enqueue(project_id=project.id, job_id=job.id)
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").data["queue"]["state"] == "QUEUED"


def test_worker_reclaims_expired_lease():
    repo = InMemoryRepository()
    project, job = _job(repo)
    queue = InProcessDocumentJobQueue(repo, lease_seconds=0)
    queue.enqueue(project_id=project.id, job_id=job.id)
    first = queue.claim()
    assert first is not None
    claimed = queue.claim()
    assert claimed is not None
    assert claimed.job_id == job.id


def test_completed_job_is_idempotent():
    repo = InMemoryRepository()
    project, job = _job(repo)
    queue = InProcessDocumentJobQueue(repo)
    queue.enqueue(project_id=project.id, job_id=job.id)
    queue.claim()
    queue.complete(job.id)
    queue.complete(job.id)
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").status == "COMPLETED"


def test_invalid_document_not_retried_forever():
    repo = InMemoryRepository()
    project, job = _job(repo)
    queue = InProcessDocumentJobQueue(repo)
    queue.enqueue(project_id=project.id, job_id=job.id)
    queue.retry(job.id, "UNSUPPORTED_DOCUMENT")
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").status == "FAILED"


def test_transient_error_retries():
    repo = InMemoryRepository()
    project, job = _job(repo)
    queue = InProcessDocumentJobQueue(repo)
    queue.enqueue(project_id=project.id, job_id=job.id)
    queue.retry(job.id, "OBJECT_STORE_FAILURE")
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").status == "RETRY_WAIT"


def test_retry_limit_enters_dead_letter():
    repo = InMemoryRepository()
    project, job = _job(repo)
    queue = InProcessDocumentJobQueue(repo)
    queue.enqueue(project_id=project.id, job_id=job.id)
    queue.retry(job.id, "WORKER_CRASH")
    queue.retry(job.id, "WORKER_CRASH")
    queue.retry(job.id, "WORKER_CRASH")
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").status == "DEAD_LETTER"

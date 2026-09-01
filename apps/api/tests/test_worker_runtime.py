from __future__ import annotations

import threading
import time
from pathlib import Path

from apps.worker.main import run_once
from packages.ctf_domain.document_intelligence import (
    PERMANENT_FAILURE,
    SUCCESS,
    DocumentProcessResult,
)
from packages.ctf_domain.job_queue import InProcessDocumentJobQueue
from packages.ctf_domain.repository import (
    InMemoryRepository,
    SQLAlchemySnapshotRepository,
    merge_worker_snapshot,
)


def _queued_job(repo: InMemoryRepository):
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "doc", {})
    live = repo.projects[project.id]
    job = repo.create_resource(live, "DOCUMENT_JOB", {"status": "QUEUED"}, status="QUEUED")
    return live, job


def test_failed_domain_job_does_not_complete_queue():
    repo = InMemoryRepository()
    project, job = _queued_job(repo)
    queue = InProcessDocumentJobQueue(repo)

    class FailedIntelligence:
        repository = repo

        def process(self, project_id, job_id):
            record = repo.get_resource(project, job_id, "DOCUMENT_JOB")
            record.status = "FAILED"
            record.data["status"] = "FAILED"
            return DocumentProcessResult(PERMANENT_FAILURE, "CHECKSUM_MISMATCH", "bad checksum")

    queue.enqueue(project_id=project.id, job_id=job.id)
    assert run_once(queue=queue, intelligence=FailedIntelligence()) is True
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").status == "FAILED"
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").data["queue"]["state"] == "FAILED"


def test_successful_process_completes_queue():
    repo = InMemoryRepository()
    project, job = _queued_job(repo)
    queue = InProcessDocumentJobQueue(repo)

    class Ok:
        repository = repo

        def process(self, project_id, job_id):
            record = repo.get_resource(project, job_id, "DOCUMENT_JOB")
            record.status = "COMPLETED"
            record.data["status"] = "COMPLETED"
            return DocumentProcessResult(SUCCESS)

    queue.enqueue(project_id=project.id, job_id=job.id)
    assert run_once(queue=queue, intelligence=Ok()) is True
    assert repo.get_resource(project, job.id, "DOCUMENT_JOB").status == "COMPLETED"


def test_lease_heartbeat_prevents_reclaim_during_long_job():
    repo = InMemoryRepository()
    project, job = _queued_job(repo)
    queue = InProcessDocumentJobQueue(repo, lease_seconds=1)

    class Slow:
        repository = repo

        def process(self, project_id, job_id):
            time.sleep(1.4)
            return DocumentProcessResult(SUCCESS)

    claimed_during: list = []

    def try_claim() -> None:
        time.sleep(0.6)
        claimed_during.append(InProcessDocumentJobQueue(repo, lease_seconds=1).claim("other"))

    queue.enqueue(project_id=project.id, job_id=job.id)
    watcher = threading.Thread(target=try_claim, daemon=True)
    watcher.start()
    assert run_once(queue=queue, intelligence=Slow(), heartbeat_seconds=0.2) is True
    watcher.join(timeout=2)
    assert claimed_during
    assert claimed_during[0] is None


def test_expired_lease_can_be_recovered_after_crash():
    repo = InMemoryRepository()
    project, job = _queued_job(repo)
    queue = InProcessDocumentJobQueue(repo, lease_seconds=0)
    queue.enqueue(project_id=project.id, job_id=job.id)
    first = queue.claim("crashed")
    assert first is not None
    record = repo.get_resource(project, job.id, "DOCUMENT_JOB")
    record.data.setdefault("queue", {})["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    recovered = queue.claim("recovery")
    assert recovered is not None
    assert recovered.job_id == job.id


def test_worker_merge_does_not_overwrite_newer_api_state(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'ctf.sqlite'}"
    api = SQLAlchemySnapshotRepository(url)
    session = api.create_session("tenant")
    project = api.create_project(session, "CREATION", "PROBLEM", "live", {})
    live = api.projects[project.id]
    api.create_resource(live, "REALITY", {"text": "from-api"}, status="CONFIRMED")
    api.create_resource(live, "DOCUMENT_JOB", {"status": "QUEUED"}, status="QUEUED")
    api.persist()
    worker = SQLAlchemySnapshotRepository(url)
    worker_live = worker.projects[project.id]
    worker.create_resource(worker_live, "DOCUMENT_CHUNK", {"text": "parsed"}, status="PARSED")
    api.create_resource(api.projects[project.id], "QUESTION", {"text": "newer-api"}, status="CONFIRMED")
    api.persist()
    worker.persist_worker_delta()
    api.refresh()
    kinds = {item.kind for item in api.resources.values() if item.project_id == project.id}
    assert "QUESTION" in kinds
    assert "DOCUMENT_CHUNK" in kinds
    assert "REALITY" in kinds
    api.close()
    worker.close()


def test_merge_worker_snapshot_keeps_api_resources():
    latest = {
        "resources": [{"id": "a", "kind": "QUESTION", "data": {}}],
        "project_resources": {"p": ["a"]},
        "audit_events": [{"id": "aud1"}],
        "projects": [{"id": "p", "memory": {"claims": []}}],
    }
    incoming = {
        "resources": [{"id": "b", "kind": "DOCUMENT_CHUNK", "data": {"text": "x"}}],
        "project_resources": {"p": ["b"]},
        "audit_events": [{"id": "aud2"}],
        "projects": [{"id": "p", "memory": {"claims": [{"id": "c1"}]}}],
    }
    merged = merge_worker_snapshot(latest, incoming)
    kinds = {item["kind"] for item in merged["resources"]}
    assert kinds == {"QUESTION", "DOCUMENT_CHUNK"}
    assert "a" in merged["project_resources"]["p"]
    assert "b" in merged["project_resources"]["p"]


def test_two_in_process_workers_cannot_claim_the_same_job():
    repo = InMemoryRepository()
    project, job = _queued_job(repo)
    first = InProcessDocumentJobQueue(repo, lease_seconds=30)
    second = InProcessDocumentJobQueue(repo, lease_seconds=30)
    first.enqueue(project_id=project.id, job_id=job.id)
    claimed = [first.claim("w1"), second.claim("w2")]
    winners = [item for item in claimed if item is not None]
    assert len(winners) == 1
    assert winners[0].job_id == job.id

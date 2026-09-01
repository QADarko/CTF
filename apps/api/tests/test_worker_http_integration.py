from __future__ import annotations

import os
import time

import httpx
import pytest

from packages.ctf_domain.object_store import S3ObjectStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.worker,
    pytest.mark.skipif(
        not os.getenv("CTF_LIVE_WORKER_TEST"),
        reason="Set CTF_LIVE_WORKER_TEST=1 against a live API+worker to run worker HTTP integration.",
    ),
]

BASE = os.getenv("CTF_WORKER_HTTP_BASE", "http://127.0.0.1:8080").rstrip("/")
API = f"{BASE}/api/v1"


def _store() -> S3ObjectStore:
    return S3ObjectStore(
        bucket=os.getenv("CTF_BUCKET", "ctf-private"),
        endpoint_url=os.getenv("S3_ENDPOINT"),
        region=os.getenv("S3_REGION", "us-east-1"),
        access_key=os.getenv("MINIO_ROOT_USER") or os.getenv("AWS_ACCESS_KEY_ID", ""),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD") or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    )


def _session() -> tuple[httpx.Client, dict[str, str], str]:
    client = httpx.Client(timeout=30.0)
    session = client.post(f"{API}/sessions/anonymous", json={"tenant_id": "worker-itest"}).json()
    headers = {
        "X-Session-Token": session["token"],
        "Idempotency-Key": f"worker-{os.getpid()}-{time.time()}",
    }
    created = client.post(
        f"{API}/projects",
        headers=headers,
        json={
            "entry_family": "CREATION",
            "entry_type": "PROBLEM",
            "initial_input": "Worker integration evidence.",
            "source": {"channel": "ci"},
        },
    )
    assert created.status_code == 201, created.text
    return client, headers, created.json()["id"]


def _wait_job(client: httpx.Client, headers: dict[str, str], project_id: str, job_id: str, timeout: float = 60.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"{API}/projects/{project_id}/document-jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        status = str(last.get("status") or last.get("data", {}).get("status") or "")
        if status in {"COMPLETED", "FAILED", "DEAD_LETTER"}:
            return last
        time.sleep(0.5)
    raise AssertionError(f"document job {job_id} did not finish: {last}")


def test_worker_processes_uploaded_document_and_creates_evidence():
    client, headers, project_id = _session()
    upload = client.post(
        f"{API}/projects/{project_id}/attachments",
        headers={k: v for k, v in headers.items() if k != "Idempotency-Key"} | {"Idempotency-Key": f"up-{time.time()}"},
        files={"file": ("note.txt", b"Three customers reported delays during onboarding.", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    attachment = upload.json()
    queued = client.post(
        f"{API}/projects/{project_id}/evidence/analyze-document",
        headers={k: v for k, v in headers.items() if k != "Idempotency-Key"} | {"Idempotency-Key": f"an-{time.time()}"},
        json={"data": {"attachment_id": attachment["id"]}},
    )
    assert queued.status_code == 202, queued.text
    job = _wait_job(client, headers, project_id, queued.json()["id"])
    assert job["status"] == "COMPLETED"
    claims = client.get(f"{API}/projects/{project_id}/resources/CLAIM", headers=headers).json()
    evidence = client.get(f"{API}/projects/{project_id}/resources/EVIDENCE", headers=headers).json()
    assert claims or evidence
    client.close()


def test_worker_retries_then_fails_when_object_is_missing():
    client, headers, project_id = _session()
    upload = client.post(
        f"{API}/projects/{project_id}/attachments",
        headers={k: v for k, v in headers.items() if k != "Idempotency-Key"} | {"Idempotency-Key": f"up2-{time.time()}"},
        files={"file": ("gone.txt", b"temporary evidence", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    attachment = upload.json()
    key = attachment.get("data", {}).get("object_key")
    if key:
        _store().delete(key)
    queued = client.post(
        f"{API}/projects/{project_id}/evidence/analyze-document",
        headers={k: v for k, v in headers.items() if k != "Idempotency-Key"} | {"Idempotency-Key": f"an2-{time.time()}"},
        json={"data": {"attachment_id": attachment["id"]}},
    )
    assert queued.status_code == 202, queued.text
    job = _wait_job(client, headers, project_id, queued.json()["id"], timeout=90.0)
    assert job["status"] in {"FAILED", "DEAD_LETTER", "QUEUED", "RETRY_WAIT", "PROCESSING"}
    if job["status"] in {"QUEUED", "RETRY_WAIT", "PROCESSING"}:
        time.sleep(8)
        job = _wait_job(client, headers, project_id, queued.json()["id"], timeout=60.0)
    assert job["status"] in {"FAILED", "DEAD_LETTER"}
    client.close()

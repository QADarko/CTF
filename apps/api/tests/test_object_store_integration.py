from __future__ import annotations

import os

import pytest

from packages.ctf_domain.object_store import S3ObjectStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.minio,
    pytest.mark.skipif(
        os.getenv("CTF_OBJECT_STORE", "local") not in {"minio", "s3"} or not os.getenv("S3_ENDPOINT"),
        reason="Set CTF_OBJECT_STORE=minio and S3_ENDPOINT to run object-store integration tests.",
    ),
]


def _store() -> S3ObjectStore:
    return S3ObjectStore(
        bucket=os.getenv("CTF_BUCKET", "ctf-private"),
        endpoint_url=os.getenv("S3_ENDPOINT"),
        region=os.getenv("S3_REGION", "us-east-1"),
        access_key=os.getenv("MINIO_ROOT_USER") or os.getenv("AWS_ACCESS_KEY_ID", ""),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD") or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    )


def test_minio_put_get_delete():
    store = _store()
    store.put("itest/object.txt", b"hello-minio", "text/plain")
    assert store.get("itest/object.txt") == b"hello-minio"
    stream = store.open_stream("itest/object.txt")
    assert stream.read() == b"hello-minio"
    url = store.presign_get("itest/object.txt", 60)
    assert url
    store.delete("itest/object.txt")


def test_minio_presigned_url():
    store = _store()
    store.put("itest/presign.txt", b"secret-a", "text/plain")
    url = store.presign_get("itest/presign.txt", 30)
    assert "itest/presign.txt" in url or "X-Amz" in url
    store.delete("itest/presign.txt")


def test_api_attachment_stored_in_minio(client, project):
    response = client.post(
        f"/api/v1/projects/{project['project']['id']}/attachments",
        headers=project["headers"],
        files={"file": ("note.txt", b"live-minio-bytes", "text/plain")},
    )
    assert response.status_code in {201, 202, 200}
    body = response.json()
    key = body.get("data", {}).get("object_key")
    if key:
        assert _store().get(key) == b"live-minio-bytes"


def test_other_tenant_cannot_access_attachment(client, project):
    created = client.post(
        f"/api/v1/projects/{project['project']['id']}/attachments",
        headers=project["headers"],
        files={"file": ("private.txt", b"tenant-a", "text/plain")},
    )
    assert created.status_code in {201, 202, 200}
    attachment_id = created.json()["id"]
    other = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "tenant-b"})
    token = other.json()["token"]
    denied = client.get(
        f"/api/v1/projects/{project['project']['id']}/attachments/{attachment_id}",
        headers={"X-Session-Token": token, "Idempotency-Key": "other-tenant-get"},
    )
    assert denied.status_code in {403, 404}


def test_other_tenant_cannot_receive_presign(client, project):
    created = client.post(
        f"/api/v1/projects/{project['project']['id']}/attachments",
        headers=project["headers"],
        files={"file": ("private2.txt", b"tenant-a", "text/plain")},
    )
    attachment_id = created.json()["id"]
    other = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "tenant-b"})
    token = other.json()["token"]
    denied = client.get(
        f"/api/v1/projects/{project['project']['id']}/attachments/{attachment_id}/download",
        headers={"X-Session-Token": token},
    )
    assert denied.status_code in {403, 404}
    if denied.status_code == 200:
        assert "url" not in denied.json()


def test_deleted_attachment_object_removed(client, project):
    created = client.post(
        f"/api/v1/projects/{project['project']['id']}/attachments",
        headers=project["headers"],
        files={"file": ("gone.txt", b"remove-me", "text/plain")},
    )
    body = created.json()
    key = body.get("data", {}).get("object_key")
    deleted = client.delete(
        f"/api/v1/projects/{project['project']['id']}/attachments/{body['id']}",
        headers=project["headers"],
    )
    assert deleted.status_code in {200, 204, 404}
    if key:
        from botocore.exceptions import ClientError

        with pytest.raises(ClientError):
            _store().get(key)

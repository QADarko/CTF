from __future__ import annotations

import os

import pytest

from packages.ctf_domain.backup import (
    backup_objects,
    destroy_object_store,
    list_objects,
    restore_objects,
    sha256_bytes,
)
from packages.ctf_domain.object_store import S3ObjectStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.minio,
    pytest.mark.skipif(
        os.getenv("CTF_OBJECT_STORE", "local") not in {"minio", "s3"} or not os.getenv("S3_ENDPOINT"),
        reason="Set CTF_OBJECT_STORE=minio and S3_ENDPOINT to run MinIO backup tests.",
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


def test_real_minio_backup(tmp_path):
    store = _store()
    store.put("dr/one.txt", b"alpha", "text/plain")
    meta = backup_objects(store, tmp_path)
    assert meta["object_count"] >= 1
    assert (tmp_path / "ctf-objects.tar.gz").is_file()


def test_minio_bucket_destroyed():
    store = _store()
    store.put("dr/destroy.txt", b"gone", "text/plain")
    destroyed = destroy_object_store(store)
    assert destroyed >= 1
    assert "dr/destroy.txt" not in {item["key"] for item in list_objects(store)}


def test_real_minio_restore(tmp_path):
    store = _store()
    store.put("dr/restore.txt", b"payload", "text/plain")
    backup_objects(store, tmp_path)
    destroy_object_store(store)
    restore_objects(store, tmp_path)
    assert store.get("dr/restore.txt") == b"payload"


def test_all_object_checksums_match(tmp_path):
    store = _store()
    bodies = {"dr/a.txt": b"one", "dr/b.txt": b"two-bytes"}
    for key, body in bodies.items():
        store.put(key, body, "text/plain")
    backup_objects(store, tmp_path)
    destroy_object_store(store)
    restore_objects(store, tmp_path)
    for key, body in bodies.items():
        restored = store.get(key)
        assert restored == body
        assert sha256_bytes(restored) == sha256_bytes(body)

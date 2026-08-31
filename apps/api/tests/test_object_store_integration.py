from __future__ import annotations

import os

import pytest

from packages.ctf_domain.object_store import S3ObjectStore

pytestmark = pytest.mark.skipif(
    os.getenv("CTF_OBJECT_STORE", "local") not in {"minio", "s3"} or not os.getenv("S3_ENDPOINT"),
    reason="Set CTF_OBJECT_STORE=minio and S3_ENDPOINT to run object-store integration tests.",
)


def test_minio_put_get_delete():
    store = S3ObjectStore(
        bucket=os.getenv("CTF_BUCKET", "ctf-private"),
        endpoint_url=os.getenv("S3_ENDPOINT"),
        region=os.getenv("S3_REGION", "us-east-1"),
        access_key=os.getenv("MINIO_ROOT_USER") or os.getenv("AWS_ACCESS_KEY_ID", ""),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD") or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    )
    store.put("itest/object.txt", b"hello-minio", "text/plain")
    assert store.get("itest/object.txt") == b"hello-minio"
    stream = store.open_stream("itest/object.txt")
    assert stream.read() == b"hello-minio"
    url = store.presign_get("itest/object.txt", 60)
    assert url
    store.delete("itest/object.txt")

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Protocol


class ObjectStore(Protocol):
    """Private binary storage; callers retain tenant-scoped metadata."""

    backend: str

    def put(self, key: str, content: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def open_stream(self, key: str) -> BinaryIO: ...

    def presign_get(self, key: str, expires_seconds: int) -> str | None: ...


class LocalObjectStore:
    backend = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("Object key escapes the configured storage root.")
        return target

    def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def open_stream(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def presign_get(self, key: str, expires_seconds: int) -> str | None:
        del key, expires_seconds
        return None


class S3ObjectStore:
    """S3-compatible private bucket adapter, including MinIO."""

    backend = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def open_stream(self, key: str) -> BinaryIO:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def presign_get(self, key: str, expires_seconds: int) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )


def create_object_store(selection: str | None = None) -> ObjectStore:
    backend = (selection or os.getenv("CTF_OBJECT_STORE", "local")).lower()
    if backend == "local":
        return LocalObjectStore(os.getenv("CTF_OBJECT_STORE_PATH", ".ctf-objects"))
    if backend in {"s3", "minio"}:
        return S3ObjectStore(
            bucket=os.getenv("CTF_BUCKET", "ctf-private"),
            endpoint_url=os.getenv("S3_ENDPOINT"),
            region=os.getenv("S3_REGION", "us-east-1"),
            access_key=os.getenv("S3_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER"),
            secret_key=os.getenv("S3_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD"),
        )
    raise ValueError(f"Unsupported CTF_OBJECT_STORE backend: {backend}")


object_store = create_object_store()

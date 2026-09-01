from __future__ import annotations

import gzip
import hashlib
import os
from copy import deepcopy
from pathlib import Path

import pytest

from packages.ctf_domain.backup import (
    backup_objects,
    restore_objects,
    verify_manifest,
    write_manifest,
)
from packages.ctf_domain.object_store import S3ObjectStore
from packages.ctf_domain.repository import SQLAlchemySnapshotRepository
from scripts.restore.verify_restore import verify_restore

pytestmark = pytest.mark.skipif(
    (
        not os.getenv("CTF_TEST_POSTGRES_URL")
        or os.getenv("CTF_OBJECT_STORE", "local") not in {"minio", "s3"}
        or not os.getenv("S3_ENDPOINT")
    )
    and not os.getenv("CTF_LIVE_BACKUP_TEST"),
    reason="Set CTF_TEST_POSTGRES_URL and MinIO env to run live backup/restore tests.",
)


def _store() -> S3ObjectStore:
    return S3ObjectStore(
        bucket=os.getenv("CTF_BUCKET", "ctf-private"),
        endpoint_url=os.getenv("S3_ENDPOINT"),
        region=os.getenv("S3_REGION", "us-east-1"),
        access_key=os.getenv("MINIO_ROOT_USER") or os.getenv("AWS_ACCESS_KEY_ID", ""),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD") or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    )


def _seed(repo: SQLAlchemySnapshotRepository, store: S3ObjectStore, tenant: str, key: str, body: bytes) -> str:
    session = repo.create_session(tenant)
    project = repo.create_project(session, "CREATION", "PROBLEM", f"backup {tenant}", {})
    live = repo.projects[project.id]
    r0 = repo.create_resource(live, "REALITY", {"text": "R0"}, status="CONFIRMED")
    evidence = repo.create_resource(live, "EVIDENCE", {"statement": "measured drop-off"}, status="CONFIRMED")
    snap = repo.create_resource(live, "REALITY_SNAPSHOT", {"label": "R1"}, status="CONFIRMED")
    repo.create_resource(live, "CREATION_CYCLE", {"status": "OPEN"}, status="ACTIVE")
    store.put(key, body, "text/plain")
    repo.create_resource(
        live,
        "ATTACHMENT",
        {
            "object_key": key,
            "checksum_sha256": hashlib.sha256(body).hexdigest(),
            "original_filename": "note.txt",
        },
        status="STORED",
    )
    repo.add_link(live, "REALITY", r0.id, "REALITY_SNAPSHOT", snap.id, "SUPERSEDES")
    repo.add_link(live, "EVIDENCE", evidence.id, "REALITY", r0.id, "SUPPORTS")
    repo.ai_runs.append(
        {"id": f"airun_{tenant}", "project_id": live.id, "operation": "REALITY_UPDATE", "outcome": "SUCCEEDED"}
    )
    repo.cost_entries.append({"id": f"cost_{tenant}", "project_id": live.id, "estimated_cost_usd": "0.01"})
    repo.persist()
    return live.id


def test_live_postgres_minio_backup_and_destructive_restore(tmp_path: Path):
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    store = _store()
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    first = _seed(repo, store, "tenant-a", "tenant-a/one.txt", b"one")
    second = _seed(repo, store, "tenant-b", "tenant-b/two.txt", b"two")
    assert first != second
    payload = deepcopy(repo._payload())
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(gzip.compress(b"snapshot-placeholder"))
    meta = backup_objects(store, root)
    write_manifest(root, database_file="ctf.sql.gz", object_meta=meta)
    verify_manifest(root / "backup-manifest.json")

    store.delete("tenant-a/one.txt")
    store.delete("tenant-b/two.txt")
    repo.reset()
    assert not repo.projects

    restore_objects(store, root)
    repo._restore(payload)
    repo.persist()
    verify_restore(url, str(root), store=store)
    assert store.get("tenant-a/one.txt") == b"one"
    assert store.get("tenant-b/two.txt") == b"two"
    repo.close()

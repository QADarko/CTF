from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from packages.ctf_domain.backup import (
    backup_objects,
    restore_objects,
    verify_manifest,
    write_manifest,
)
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.object_store import LocalObjectStore


def _local_store(tmp_path: Path) -> LocalObjectStore:
    store = LocalObjectStore(tmp_path / "objects-live")
    store.put("tenant-a/att-1.bin", b"attachment-bytes", "application/octet-stream")
    return store


def test_minio_objects_are_in_backup(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    meta = backup_objects(store, root)
    assert meta["object_count"] == 1
    inventory = json.loads((root / "objects.json").read_text(encoding="utf-8"))
    assert inventory[0]["key"] == "tenant-a/att-1.bin"


def test_backup_manifest_contains_object_inventory(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    (root).mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    meta = backup_objects(store, root)
    path = write_manifest(root, database_file="ctf.sql.gz", object_meta=meta)
    manifest = verify_manifest(path)
    assert manifest["format_version"] == "1.1"
    assert manifest["object_store"]["manifest"] == "objects.json"
    assert manifest["object_store"]["object_count"] == 1


def test_restore_recreates_minio_objects(tmp_path: Path):
    source = _local_store(tmp_path)
    root = tmp_path / "backup"
    (root / "ctf.sql.gz").parent.mkdir(parents=True, exist_ok=True)
    (root / "ctf.sql.gz").write_bytes(b"sql")
    backup_objects(source, root)
    dest = LocalObjectStore(tmp_path / "objects-restored")
    restore_objects(dest, root)
    assert dest.get("tenant-a/att-1.bin") == b"attachment-bytes"


def test_restored_attachment_checksum_matches(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    backup_objects(store, root)
    dest = LocalObjectStore(tmp_path / "restored")
    inventory = restore_objects(dest, root)
    assert inventory[0]["checksum"] == hashlib.sha256(b"attachment-bytes").hexdigest()


def test_full_project_survives_backup_restore(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"project-state")
    meta = backup_objects(store, root)
    write_manifest(root, database_file="ctf.sql.gz", object_meta=meta)
    verify_manifest(root / "backup-manifest.json")
    dest = LocalObjectStore(tmp_path / "restored")
    restore_objects(dest, root)
    assert dest.get("tenant-a/att-1.bin") == b"attachment-bytes"


def test_missing_object_fails_restore_verification(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    backup_objects(store, root)
    inventory = json.loads((root / "objects.json").read_text(encoding="utf-8"))
    inventory.append({"key": "missing.bin", "size": 1, "checksum": "00", "etag": None})
    (root / "objects.json").write_text(json.dumps(inventory), encoding="utf-8")
    dest = LocalObjectStore(tmp_path / "restored")
    with pytest.raises((DomainError, FileNotFoundError)):
        restore_objects(dest, root)


def test_corrupted_database_backup_fails_verification(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    meta = backup_objects(store, root)
    path = write_manifest(root, database_file="ctf.sql.gz", object_meta=meta)
    (root / "ctf.sql.gz").write_bytes(b"corrupted")
    with pytest.raises(DomainError) as caught:
        verify_manifest(path)
    assert caught.value.code == "BACKUP_INTEGRITY_FAILED"

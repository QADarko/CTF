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


def test_modified_attachment_checksum_fails_restore(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    backup_objects(store, root)
    inventory = json.loads((root / "objects.json").read_text(encoding="utf-8"))
    inventory[0]["checksum"] = "deadbeef"
    (root / "objects.json").write_text(json.dumps(inventory), encoding="utf-8")
    dest = LocalObjectStore(tmp_path / "restored")
    with pytest.raises(DomainError) as caught:
        restore_objects(dest, root)
    assert caught.value.code == "RESTORE_INTEGRITY_FAILED"


def test_invalid_manifest_fails_verification(tmp_path: Path):
    path = tmp_path / "backup-manifest.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises((DomainError, KeyError, TypeError)):
        verify_manifest(path)


def test_unsupported_backup_format_fails(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    meta = backup_objects(store, root)
    path = write_manifest(root, database_file="ctf.sql.gz", object_meta=meta)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["format_version"] = "9.9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainError) as caught:
        verify_manifest(path)
    assert caught.value.code == "BACKUP_INTEGRITY_FAILED"


def test_partial_restore_fails_when_object_missing(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    (root / "ctf.sql.gz").write_bytes(b"sql")
    backup_objects(store, root)
    dest = LocalObjectStore(tmp_path / "restored")
    objects_dir = root / "objects"
    for path in objects_dir.rglob("*"):
        if path.is_file():
            path.unlink()
    archive = root / "ctf-objects.tar.gz"
    if archive.is_file():
        archive.unlink()
    with pytest.raises((DomainError, FileNotFoundError)):
        restore_objects(dest, root)


def test_verify_restore_checks_every_project_not_only_the_first(tmp_path: Path):
    from packages.ctf_domain.repository import SQLAlchemySnapshotRepository
    from scripts.restore.verify_restore import verify_restore

    url = f"sqlite:///{tmp_path / 'restore.sqlite'}"
    repo = SQLAlchemySnapshotRepository(url)
    first_session = repo.create_session("tenant-a")
    first = repo.create_project(first_session, "CREATION", "PROBLEM", "one", {})
    live_a = repo.projects[first.id]
    r0 = repo.create_resource(live_a, "REALITY", {"text": "R0"}, status="CONFIRMED")
    repo.create_resource(live_a, "REALITY_SNAPSHOT", {"label": "R1"}, status="CONFIRMED")
    repo.create_resource(live_a, "CREATION_CYCLE", {"status": "OPEN"}, status="ACTIVE")
    evidence = repo.create_resource(live_a, "EVIDENCE", {"statement": "drop-off"}, status="CONFIRMED")
    repo.add_link(live_a, "EVIDENCE", evidence.id, "REALITY", r0.id, "SUPPORTS")
    repo.ai_runs.append({"id": "airun_a", "project_id": live_a.id, "operation": "REALITY_UPDATE"})
    repo.cost_entries.append({"id": "cost_a", "project_id": live_a.id, "estimated_cost_usd": "0.01"})
    second_session = repo.create_session("tenant-b")
    second = repo.create_project(second_session, "CREATION", "PROBLEM", "two", {})
    live_b = repo.projects[second.id]
    repo.create_resource(live_b, "REALITY", {"text": "other"}, status="CONFIRMED")
    repo.persist()
    with pytest.raises(SystemExit, match="missing"):
        verify_restore(url)
    repo.create_resource(live_b, "REALITY_SNAPSHOT", {"label": "R1"}, status="CONFIRMED")
    repo.create_resource(live_b, "CREATION_CYCLE", {"status": "OPEN"}, status="ACTIVE")
    repo.create_resource(live_b, "EVIDENCE", {"statement": "other"}, status="CONFIRMED")
    repo.add_link(live_b, "REALITY", repo.list_resources(live_b, "REALITY")[0].id, "REALITY_SNAPSHOT", repo.list_resources(live_b, "REALITY_SNAPSHOT")[0].id, "SUPERSEDES")
    repo.ai_runs.append({"id": "airun_b", "project_id": live_b.id, "operation": "R1_GENERATION"})
    repo.cost_entries.append({"id": "cost_b", "project_id": live_b.id, "estimated_cost_usd": "0.02"})
    repo.persist()
    verify_restore(url)
    repo.close()


def _malicious_tar(path: Path, name: str, *, symlink: str | None = None) -> None:
    import tarfile

    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        if symlink is not None:
            info.type = tarfile.SYMTYPE
            info.linkname = symlink
            tar.addfile(info)
            return
        payload = b"evil"
        info.size = len(payload)
        import io

        tar.addfile(info, io.BytesIO(payload))


def test_tar_path_traversal_rejected(tmp_path: Path):
    from packages.ctf_domain.backup import safe_extract_tar

    archive = tmp_path / "evil.tar.gz"
    _malicious_tar(archive, "../outside.txt")
    with pytest.raises(DomainError) as caught:
        safe_extract_tar(archive, tmp_path / "restore")
    assert caught.value.code == "BACKUP_PATH_TRAVERSAL"


def test_absolute_tar_path_rejected(tmp_path: Path):
    from packages.ctf_domain.backup import safe_extract_tar

    archive = tmp_path / "abs.tar.gz"
    _malicious_tar(archive, "/tmp/absolute.txt")
    with pytest.raises(DomainError) as caught:
        safe_extract_tar(archive, tmp_path / "restore")
    assert caught.value.code == "BACKUP_PATH_TRAVERSAL"


def test_symlink_escape_rejected(tmp_path: Path):
    from packages.ctf_domain.backup import safe_extract_tar

    archive = tmp_path / "link.tar.gz"
    _malicious_tar(archive, "objects/link", symlink="../secret")
    with pytest.raises(DomainError) as caught:
        safe_extract_tar(archive, tmp_path / "restore")
    assert caught.value.code == "BACKUP_SYMLINK_REJECTED"


def test_valid_backup_archive_extracts(tmp_path: Path):
    store = _local_store(tmp_path)
    root = tmp_path / "backup"
    root.mkdir()
    backup_objects(store, root)
    dest = LocalObjectStore(tmp_path / "ok-restore")
    restore_objects(dest, root)
    assert dest.get("tenant-a/att-1.bin") == b"attachment-bytes"

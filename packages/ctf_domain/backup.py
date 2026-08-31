"""Coordinated PostgreSQL + object-store backup/restore (CTF-016A)."""

from __future__ import annotations

import hashlib
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import DomainError
from .object_store import LocalObjectStore, ObjectStore, S3ObjectStore

FORMAT_VERSION = "1.1"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def list_objects(store: ObjectStore) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(store, LocalObjectStore):
        for path in sorted(store.root.rglob("*")):
            if path.is_file() and not path.name.endswith(".tmp"):
                key = path.relative_to(store.root).as_posix()
                content = path.read_bytes()
                items.append({"key": key, "size": len(content), "checksum": sha256_bytes(content), "etag": None})
        return items
    if isinstance(store, S3ObjectStore):
        paginator = store.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=store.bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                body = store.get(key)
                items.append(
                    {
                        "key": key,
                        "size": int(obj.get("Size", len(body))),
                        "checksum": sha256_bytes(body),
                        "etag": str(obj.get("ETag", "")).strip('"') or None,
                    }
                )
        return items
    raise DomainError("BACKUP_INTEGRITY_FAILED", "Unsupported object store for backup.", 500)


def backup_objects(store: ObjectStore, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    objects_dir = root / "objects"
    objects_dir.mkdir(exist_ok=True)
    inventory = list_objects(store)
    for item in inventory:
        content = store.get(item["key"])
        target = objects_dir / item["key"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (root / "objects.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    archive = root / "ctf-objects.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(objects_dir, arcname="objects")
        tar.add(root / "objects.json", arcname="objects.json")
    provider = getattr(store, "backend", "local")
    bucket = getattr(store, "bucket", "local")
    return {
        "provider": provider,
        "bucket": bucket,
        "object_count": len(inventory),
        "archive": archive.name,
        "sha256": sha256_file(archive),
        "manifest": "objects.json",
    }


def write_manifest(root: Path, *, database_file: str, object_meta: dict[str, Any]) -> Path:
    manifest = {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "ctf_version": "0.1.0",
        "database": {"file": database_file, "sha256": sha256_file(root / database_file)},
        "object_store": object_meta,
    }
    path = root / "backup-manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def verify_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format_version") not in {"1.0", FORMAT_VERSION}:
        raise DomainError("BACKUP_INTEGRITY_FAILED", "Unsupported backup format.", 400)
    root = path.parent
    database = root / manifest["database"]["file"]
    if not database.is_file() or sha256_file(database) != manifest["database"]["sha256"]:
        raise DomainError("BACKUP_INTEGRITY_FAILED", "Database backup checksum mismatch.", 400)
    objects = manifest.get("object_store") or {}
    archive = root / objects.get("archive", "ctf-objects.tar.gz")
    if not archive.is_file() or sha256_file(archive) != objects.get("sha256"):
        raise DomainError("BACKUP_INTEGRITY_FAILED", "Object-store backup checksum mismatch.", 400)
    inventory_name = objects.get("manifest")
    if inventory_name:
        inventory_path = root / inventory_name
        if not inventory_path.is_file():
            with tarfile.open(archive, "r:gz") as tar:
                member = tar.extractfile("objects.json")
                if member is None:
                    raise DomainError("BACKUP_INTEGRITY_FAILED", "Object inventory missing.", 400)
                inventory = json.loads(member.read().decode("utf-8"))
        else:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        if int(objects.get("object_count", 0)) != len(inventory):
            raise DomainError("BACKUP_INTEGRITY_FAILED", "Object inventory count mismatch.", 400)
    return manifest


def restore_objects(store: ObjectStore, root: Path) -> list[dict[str, Any]]:
    archive = root / "ctf-objects.tar.gz"
    extract = root / "_restore_objects"
    extract.mkdir(exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(extract)
    inventory_path = root / "objects.json"
    if not inventory_path.is_file():
        inventory_path = extract / "objects.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.is_file() else []
    objects_dir = extract / "objects"
    if not objects_dir.is_dir():
        objects_dir = root / "objects"
    for item in inventory:
        payload = (objects_dir / item["key"]).read_bytes()
        if sha256_bytes(payload) != item["checksum"]:
            raise DomainError("RESTORE_INTEGRITY_FAILED", f"Object checksum mismatch for {item['key']}.", 400)
        store.put(item["key"], payload, "application/octet-stream")
    return inventory

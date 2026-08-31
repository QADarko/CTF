from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def verify_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != "1.0":
        raise SystemExit("BACKUP_INTEGRITY_FAILED: unsupported format")
    root = path.parent
    database = root / manifest["database"]["file"]
    objects = root / manifest["object_store"]["archive"]
    if not database.is_file() or not objects.is_file():
        raise SystemExit("BACKUP_INTEGRITY_FAILED: missing backup artifacts")
    if _sha256(database) != manifest["database"]["sha256"]:
        raise SystemExit("BACKUP_INTEGRITY_FAILED: database checksum mismatch")
    if _sha256(objects) != manifest["object_store"]["sha256"]:
        raise SystemExit("BACKUP_INTEGRITY_FAILED: object-store checksum mismatch")
    if int(manifest["object_store"].get("object_count", 0)) < 0:
        raise SystemExit("BACKUP_INTEGRITY_FAILED: invalid object count")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    verify_manifest(Path(sys.argv[1] if len(sys.argv) > 1 else "backup-manifest.json"))
    print("PASS backup manifest")

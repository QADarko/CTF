from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.backup.verify_backup import verify_manifest


def test_backup_manifest_requires_both_database_and_objects(tmp_path: Path):
    payload = {
        "format_version": "1.0",
        "created_at": "2026-09-01T00:00:00Z",
        "ctf_version": "0.1.0",
        "database": {"file": "ctf.sql.gz", "sha256": hashlib.sha256(b"db").hexdigest()},
        "object_store": {"archive": "ctf-objects.tar.gz", "sha256": hashlib.sha256(b"obj").hexdigest(), "object_count": 1},
    }
    (tmp_path / "ctf.sql.gz").write_bytes(b"db")
    (tmp_path / "ctf-objects.tar.gz").write_bytes(b"obj")
    (tmp_path / "backup-manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    verify_manifest(tmp_path / "backup-manifest.json")

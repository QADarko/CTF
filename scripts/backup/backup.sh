#!/usr/bin/env bash
set -euo pipefail
# Coordinated maintenance-window backup. Stop mutating traffic before running.
ROOT="${1:-./backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ROOT"
pg_dump --no-owner --format=plain "$CTF_DATABASE_URL" | gzip > "$ROOT/ctf.sql.gz"
# Mirror the private bucket; mc/aws must already be authenticated.
if [[ -n "${CTF_BUCKET:-}" ]]; then
  tar -czf "$ROOT/ctf-objects.tar.gz" -C "${CTF_OBJECT_STORE_PATH:-.ctf-objects}" .
else
  tar -czf "$ROOT/ctf-objects.tar.gz" -C "${CTF_OBJECT_STORE_PATH:-.ctf-objects}" .
fi
python - <<PY
import hashlib, json, os
from pathlib import Path
root = Path(r"$ROOT")
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {
    "format_version": "1.0",
    "created_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    "ctf_version": "0.1.0",
    "database": {"file": "ctf.sql.gz", "sha256": sha(root / "ctf.sql.gz")},
    "object_store": {
        "archive": "ctf-objects.tar.gz",
        "sha256": sha(root / "ctf-objects.tar.gz"),
        "object_count": int(os.getenv("CTF_BACKUP_OBJECT_COUNT", "0")),
    },
}
(root / "backup-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(root / "backup-manifest.json")
PY
python scripts/backup/verify_backup.py "$ROOT/backup-manifest.json"

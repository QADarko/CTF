#!/usr/bin/env bash
set -euo pipefail
# Coordinated maintenance-window backup. Stop mutating traffic and workers first.
ROOT="${1:-./backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ROOT"
if [[ -z "${CTF_DATABASE_URL:-}" ]]; then
  echo "CTF_DATABASE_URL is required" >&2
  exit 1
fi
pg_dump --no-owner --format=plain "$CTF_DATABASE_URL" | gzip > "$ROOT/ctf.sql.gz"

python - <<PY
from pathlib import Path
from packages.ctf_domain.backup import backup_objects, write_manifest
from packages.ctf_domain.object_store import object_store
root = Path(r"$ROOT")
meta = backup_objects(object_store, root)
write_manifest(root, database_file="ctf.sql.gz", object_meta=meta)
print(root / "backup-manifest.json")
PY
python scripts/backup/verify_backup.py "$ROOT/backup-manifest.json"

#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:?backup directory required}"
python scripts/backup/verify_backup.py "$ROOT/backup-manifest.json"
gunzip -c "$ROOT/ctf.sql.gz" | psql "$CTF_DATABASE_URL"
python - <<PY
from pathlib import Path
from packages.ctf_domain.backup import restore_objects
from packages.ctf_domain.object_store import object_store
restore_objects(object_store, Path(r"$ROOT"))
PY
python scripts/restore/verify_restore.py "$CTF_DATABASE_URL" "$ROOT"

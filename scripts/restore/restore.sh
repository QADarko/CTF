#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:?backup directory required}"
python scripts/backup/verify_backup.py "$ROOT/backup-manifest.json"
gunzip -c "$ROOT/ctf.sql.gz" | psql "$CTF_DATABASE_URL"
mkdir -p "${CTF_OBJECT_STORE_PATH:-.ctf-objects}"
tar -xzf "$ROOT/ctf-objects.tar.gz" -C "${CTF_OBJECT_STORE_PATH:-.ctf-objects}"
python scripts/restore/verify_restore.py "$CTF_DATABASE_URL"

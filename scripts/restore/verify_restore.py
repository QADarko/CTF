from __future__ import annotations

import json
import sys
from pathlib import Path

from packages.ctf_domain.backup import sha256_bytes
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import create_repository

REQUIRED_KINDS = (
    "REALITY",
    "REALITY_SNAPSHOT",
    "CREATION_CYCLE",
)


def verify_restore(database_url: str, backup_root: str | None = None) -> None:
    repo = create_repository(database_url)
    if not repo.projects:
        raise SystemExit("RESTORE_INTEGRITY_FAILED: no projects restored")
    project = next(iter(repo.projects.values()))
    for kind in REQUIRED_KINDS:
        if not repo.list_resources(project, kind):
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: missing {kind}")
    if not repo.memory_versions.get(project.id):
        raise SystemExit("RESTORE_INTEGRITY_FAILED: missing memory history")
    if not repo.creation_links:
        raise SystemExit("RESTORE_INTEGRITY_FAILED: missing genealogy")
    if not repo.ai_runs:
        raise SystemExit("RESTORE_INTEGRITY_FAILED: missing AI runs")
    if not repo.cost_entries:
        raise SystemExit("RESTORE_INTEGRITY_FAILED: missing cost ledger")
    if not repo.audit_events:
        raise SystemExit("RESTORE_INTEGRITY_FAILED: missing audit")
    attachments = repo.list_resources(project, "ATTACHMENT")
    if backup_root:
        inventory_path = Path(backup_root) / "objects.json"
        if inventory_path.is_file():
            inventory = {item["key"]: item for item in json.loads(inventory_path.read_text(encoding="utf-8"))}
            for attachment in attachments:
                key = attachment.data.get("object_key")
                expected = attachment.data.get("checksum_sha256")
                if key and expected:
                    if key not in inventory:
                        raise SystemExit(f"RESTORE_INTEGRITY_FAILED: missing object {key}")
                    if sha256_bytes(object_store.get(key)) != expected:
                        raise SystemExit("RESTORE_INTEGRITY_FAILED: attachment checksum mismatch")
    print("PASS restore integrity")


if __name__ == "__main__":
    verify_restore(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else None)

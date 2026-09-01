from __future__ import annotations

import json
import sys
from pathlib import Path

from packages.ctf_domain.backup import sha256_bytes
from packages.ctf_domain.object_store import ObjectStore, object_store
from packages.ctf_domain.repository import create_repository

REQUIRED_KINDS = (
    "REALITY",
    "REALITY_SNAPSHOT",
    "CREATION_CYCLE",
    "EVIDENCE",
)


def verify_restore(
    database_url: str,
    backup_root: str | None = None,
    store: ObjectStore | None = None,
) -> None:
    repo = create_repository(database_url)
    live_store = store or object_store
    if not repo.projects:
        raise SystemExit("RESTORE_INTEGRITY_FAILED: no projects restored")
    for project in repo.projects.values():
        for kind in REQUIRED_KINDS:
            if not repo.list_resources(project, kind):
                raise SystemExit(f"RESTORE_INTEGRITY_FAILED: project {project.id} missing {kind}")
        if not repo.memory_versions.get(project.id):
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: project {project.id} missing memory history")
        if not [link for link in repo.creation_links if link.get("project_id") == project.id]:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: project {project.id} missing genealogy")
        if not [item for item in repo.ai_runs if item.get("project_id") == project.id]:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: project {project.id} missing AI runs")
        if not [item for item in repo.cost_entries if item.get("project_id") == project.id]:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: project {project.id} missing cost ledger")
        if not [item for item in repo.audit_events if getattr(item, "project_id", None) == project.id]:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: project {project.id} missing audit")
        if backup_root:
            _verify_attachments(project, repo.list_resources(project, "ATTACHMENT"), Path(backup_root), live_store)
    if backup_root:
        _verify_object_inventory(Path(backup_root), repo, live_store)
    print("PASS restore integrity")


def _verify_attachments(project, attachments, backup_root: Path, store: ObjectStore) -> None:
    inventory_path = backup_root / "objects.json"
    if not inventory_path.is_file():
        return
    inventory = {item["key"]: item for item in json.loads(inventory_path.read_text(encoding="utf-8"))}
    tenant = project.tenant_id
    for attachment in attachments:
        key = attachment.data.get("object_key")
        expected = attachment.data.get("checksum_sha256")
        if not key:
            continue
        if key not in inventory:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: missing object {key}")
        try:
            body = store.get(key)
        except Exception as exc:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: object {key} unavailable ({exc})") from exc
        if expected and sha256_bytes(body) != expected:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: checksum mismatch for {key}")
        if inventory[key].get("size") not in {None, len(body)}:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: size mismatch for {key}")
        if tenant and "/" in str(key):
            prefix = str(key).split("/", 1)[0]
            if prefix not in {tenant, project.id}:
                raise SystemExit(f"RESTORE_INTEGRITY_FAILED: object {key} is not isolated to tenant {tenant}")


def _verify_object_inventory(backup_root: Path, repo, store: ObjectStore) -> None:
    inventory_path = backup_root / "objects.json"
    if not inventory_path.is_file():
        raise SystemExit("RESTORE_INTEGRITY_FAILED: object inventory missing")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    live_keys = set()
    for project in repo.projects.values():
        for attachment in repo.list_resources(project, "ATTACHMENT"):
            key = attachment.data.get("object_key")
            if key:
                live_keys.add(key)
    stored_keys = {item["key"] for item in inventory}
    missing = live_keys - stored_keys
    if missing:
        raise SystemExit(f"RESTORE_INTEGRITY_FAILED: missing objects {sorted(missing)}")
    for item in inventory:
        try:
            body = store.get(item["key"])
        except Exception as exc:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: corrupted object {item['key']} ({exc})") from exc
        if sha256_bytes(body) != item["checksum"]:
            raise SystemExit(f"RESTORE_INTEGRITY_FAILED: corrupted object {item['key']}")


if __name__ == "__main__":
    verify_restore(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else None)

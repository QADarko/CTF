from __future__ import annotations

import sys

from packages.ctf_domain.repository import create_repository

REQUIRED_KINDS = (
    "REALITY",
    "REALITY_SNAPSHOT",
    "CREATION_CYCLE",
)


def verify_restore(database_url: str) -> None:
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
    print("PASS restore integrity")


if __name__ == "__main__":
    verify_restore(sys.argv[1] if len(sys.argv) > 1 else "")

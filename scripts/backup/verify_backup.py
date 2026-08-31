from __future__ import annotations

import sys
from pathlib import Path

from packages.ctf_domain.backup import verify_manifest
from packages.ctf_domain.errors import DomainError

if __name__ == "__main__":
    try:
        verify_manifest(Path(sys.argv[1] if len(sys.argv) > 1 else "backup-manifest.json"))
    except DomainError as exc:
        raise SystemExit(f"{exc.code}: {exc}") from exc
    print("PASS backup manifest")

# CTF Full V1 backend

Python 3.12 modular FastAPI monolith. The runtime repository defaults to memory,
or uses a durable SQLAlchemy snapshot when `CTF_DATABASE_URL` is set. Docker
Compose configures PostgreSQL plus private MinIO attachment storage.

Run from the repository root:

```powershell
python -m pip install -e ".[test]"
python -m uvicorn apps.api.app.main:app --reload
python -m pytest
```

Useful local selections:

```powershell
$env:CTF_DATABASE_URL = "sqlite:///./ctf.db"
$env:CTF_OBJECT_STORE = "local"
$env:CTF_OBJECT_STORE_PATH = ".ctf-objects"
python -m alembic upgrade head
```

Create an anonymous session, then pass its token as `X-Session-Token` on all
project requests. Mutation endpoints accept `expected_version` for optimistic
locking. All consequential API mutations require `Idempotency-Key` outside
tests by default; matching replays are stable and changed payloads conflict.
Confirmed consequential records reject in-place edits and use the explicit
`.../{resource_id}/supersede` route to preserve history.

Request/upload bounds, per-tenant/session rate limits, daily tenant AI
token/cost reservations, safe response headers, filename sanitization and
malware scanning are configured with the `CTF_*` variables in `.env.example`.
Local attachment downloads stream after ownership/scan checks; S3-compatible
backends issue audited short-lived presigned URLs. The `noop` scanner is a
development-only seam, not a malware-safety claim.

No provider adapter makes a network AI call. `/api/v1/ai/routes/*` resolves
capability contracts and `/api/v1/ai/usage` records provider-reported usage
against a versioned price snapshot.

The snapshot implementation intentionally supports one API process. Do not run
multiple Uvicorn workers against it until cross-process locking or a normalized
repository replaces the single aggregate row.

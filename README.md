# CTF Full V1

This repository contains a runnable CTF implementation and its architecture, security,
prompt-registry, contract and verification assets.

## Applications

- `apps/api`: FastAPI modular monolith exposing the `/api/v1` API and all 19
  human-gate rules.
- `apps/web`: Next.js 13 full-cycle workspace. It uses polished mock data by default;
  set `NEXT_PUBLIC_USE_MOCKS=false` to create a live anonymous API session and project.
- `packages/ctf_domain`: state machine, domain services, selectable repository,
  private object storage, prompt registry, AI execution/model routing and ERI support.
- `docs/openapi.yaml`: a deliberately partial contract skeleton. Its paths are relative
  to the declared `/api/v1` server URL; FastAPI's generated `/openapi.json` is the
  authoritative description of the runnable API.

## Architecture status

The checked-in `docs/capability-status.yaml` is the evidence-backed capability
inventory. Its 80 entries distinguish `IMPLEMENTED`, `PARTIAL`,
`NOT_IMPLEMENTED`, `BLOCKED_EXTERNAL`, and `DEFERRED_V1`; an implemented label
requires direct repository evidence. The web header opens the same Architecture
Status view. Mock mode uses the dated checked-in snapshot, while live mode reads:

- `GET /api/v1/system/capabilities` — public inventory, summary counts, and
  repeatable `status` / `priority` filters.
- `GET /api/v1/system/readiness` — safe release-blocker, AI, persistence,
  object-store, document-worker, KHAL, and pilot status.

Neither endpoint returns credentials, provider URLs, or private configuration.
The current inventory does not claim a completed external pilot, a live KHAL
connection, production model quality, a durable external document worker,
multi-worker database safety, a production-configured malware service, or tested
backup/restore.

## Run locally

Backend (Python 3.12):

```text
python -m pip install -e ".[test]"
python -m uvicorn apps.api.app.main:app --reload --port 8080
```

The default is intentionally in-memory for fast tests. For durable local
persistence, set `CTF_DATABASE_URL=sqlite:///./ctf.db`; PostgreSQL URLs use
`postgresql+psycopg://...`. Attachment binaries default to private local
storage under `.ctf-objects`; configure `CTF_OBJECT_STORE_PATH` to move it.

### Offline document analysis

Upload a PDF, DOCX, XLSX, UTF-8 TXT or CSV attachment, then call
`POST /api/v1/projects/{project_id}/evidence/analyze-document` with:

```json
{"data": {"attachment_id": "atta_..."}}
```

The durable job runs locally without an LLM and reports
`QUEUED → PROCESSING → COMPLETED|FAILED` through
`GET /api/v1/projects/{project_id}/document-jobs/{job_id}`. Its `data` includes
safe progress, counts and errors. Parsed metadata and paginated chunks are
available at
`GET /api/v1/projects/{project_id}/attachments/{attachment_id}/parsed`.
Extracted claims/evidence are deterministic candidates only; document text,
including prompt-like instructions, is treated solely as untrusted source text.
See `docs/architecture.md` for parser limits and the external-worker seam.

### Optional AI execution

Manual routes remain the default. Explicit providers are
`openai-compatible`, local `ollama`, and non-production `fake`; there is no
automatic fallback. OpenAI-compatible mode uses `AI_BASE_URL`, `AI_API_KEY` and
`AI_MODEL_MAP`. Ollama needs no API key and uses `OLLAMA_BASE_URL`, per-tier
model settings and `OLLAMA_TIMEOUT_SECONDS`. Registered operations are listed at
`GET /api/v1/ai/operations` and explicitly run at
`POST /api/v1/projects/{project_id}/ai/execute`. Run audit is available at
`GET /api/v1/projects/{project_id}/ai/runs`; safe provider/model health is at
`GET /api/v1/ai/readiness`.

Generator requests opt in with `"execute_ai": true`; otherwise their existing
manual persistence behavior is unchanged. AI output must be strict registered
JSON, remains `PROPOSED`/`CANDIDATE`, receives at most one schema retry, and
passes ordinary domain validation before any resource is persisted. No-provider
configuration returns `AI_PROVIDER_NOT_CONFIGURED` without affecting the core
workflow.

For zero-install AI UX testing, load `.env.fake-ai.example`; its schema-valid
operation fixtures perform no reasoning and are marked non-production. For
Ollama, load `.env.local-ai.example` after manually installing/starting the
runtime, or run `docker compose --profile local-ai up --build` with
`AI_PROVIDER=ollama` and `OLLAMA_BASE_URL=http://ollama:11434`. Local T1/T2 are
enabled; T3/T4 fail closed unless their explicit `AI_LOCAL_ALLOW_T3` /
`AI_LOCAL_ALLOW_T4` flags are enabled. See `docs/local-ai.md` for exact
PowerShell flows, model choices, hardware guidance, and limitations.

Frontend:

```text
cd apps/web
npm ci
npm run dev
```

For live API mode, set:

```text
NEXT_PUBLIC_USE_MOCKS=false
NEXT_PUBLIC_CTF_API_URL=http://localhost:8080/api/v1
```

Or run the applications and retained infrastructure services together:

```text
copy .env.example .env
docker compose up --build
```

The API is available at `http://localhost:8080`, the web app at
`http://localhost:3000`, PostgreSQL at port 5432 and MinIO at ports 9000/9001.

## Persistence

`CTF_DATABASE_URL` selects a SQLAlchemy snapshot repository that atomically
persists sessions, projects/gates/memory, resources, memory versions, audit and
genealogy records, idempotency and ERI dedupe state, AI runs, and cost entries. Compose
always selects PostgreSQL and waits for it to become healthy.

`CTF_OBJECT_STORE=local` uses private filesystem storage.
`CTF_OBJECT_STORE=minio` or `s3` uses the S3-compatible adapter; Compose selects
MinIO, creates a private bucket, and waits for initialization. The API returns
opaque object keys in tenant-scoped attachment metadata, never public URLs.
Authorized downloads stream from local storage or return a short-lived S3
presigned URL. Ownership and clean-scan state are checked before delivery and
each authorization is audited.

## Backend security controls

Outside pytest, every consequential `POST`, `PUT`, `PATCH`, and `DELETE` under
`/api` requires an `Idempotency-Key` by default. Replays return the original
successful status/body and reuse with a different body returns
`IDEMPOTENCY_CONFLICT`. `CTF_IDEMPOTENCY_POLICY=optional` is the explicit legacy
mode; `deterministic` derives a body fingerprint for keyless legacy clients.

Rate limits are per tenant/session and AI quotas are per tenant/UTC day. Both
are persisted by the snapshot repository, are suitable for one API process,
and return the stable error envelope with HTTP 429 and `Retry-After`. Request
and upload byte bounds are independent.

Attachments remain `SCANNING` until the selected scanner returns clean.
`CTF_MALWARE_SCANNER=noop` is only a development seam, `eicar-test` is
deterministic test behavior, and `clamav` uses ClamAV's network `INSTREAM`
protocol. Detected content is retained privately as `QUARANTINED` and cannot be
analyzed or downloaded.

External human validation is intentionally separate from automated acceptance.
Use `docs/pilot-validation.md` to recruit cohorts, run the five-slice protocol,
and record the human go/no-go decision. The repository is pilot-ready; it does
not claim that an external pilot has already occurred.

The snapshot adapter is designed for a single API process. It gives atomic
rollback/commit semantics within repository transactions, but does not provide
safe concurrent writes from multiple API workers. Scale-out requires database
locking or a normalized repository. Database/object-store commits also cannot
form one distributed transaction; failed uploads are compensated, while failed
binary cleanup can leave a private orphan for operational reconciliation.
Rate-limit counters and quota reservations have the same single-process
limitation; this implementation does not claim distributed enforcement.

## Validate

```text
python -m pytest
$env:CTF_DATABASE_URL="sqlite:///./test-ctf.db"; python -m pytest
python tests/verify_assets.py
openapi-spec-validator docs/openapi.yaml
ruff check apps/api packages/ctf_domain tests
docker compose config --quiet
docker compose --profile local-ai config --quiet
cd apps/web
npm run lint
npm run build
```

The DOCX specification is source material and is not modified.

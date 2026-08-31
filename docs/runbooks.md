# CTF Operations Runbooks

## Local start and smoke test

1. Copy `.env.example` to `.env` and replace all `change-me` values.
2. Run `docker compose up -d postgres minio minio-init`.
3. Verify `docker compose ps` reports PostgreSQL and MinIO healthy and `minio-init` exited successfully.
4. Optionally run placeholders: `docker compose --profile placeholders up -d`.
5. Confirm the bucket is private and PostgreSQL contains `ctf.infrastructure_metadata`.
6. Stop with `docker compose down`; add `-v` only when intentionally destroying local data.

## Database unavailable

**Signal:** health check fails, elevated connection errors, API readiness fails.

1. Freeze consequential writes; do not acknowledge gate/decision success.
2. Check capacity, connection saturation and server logs without exposing credentials.
3. Restore connectivity or fail over according to hosting controls.
4. Reconcile requests by request ID and idempotency key; never replay blindly.
5. Verify the latest gate/decision transaction is all-or-nothing and audit sequence is intact.
6. Run tenant-isolation and workflow smoke tests before reopening writes.

## Object storage unavailable

1. Disable new upload completion and signed retrieval; retain safe metadata state.
2. Never mark an attachment `STORED` until object existence/checksum is verified.
3. Restore MinIO/service connectivity and reconcile quarantined/incomplete uploads.
4. Check private-bucket policy, checksum and project ownership before re-enabling.

## Malware scanner unavailable or detection

1. Fail uploads closed when ClamAV is unavailable; do not mark metadata ready.
2. For `MALWARE_DETECTED`, retain the opaque object privately in `QUARANTINED`
   state, deny analysis/download, and record only the scanner/signature in audit.
3. Do not use `noop` outside an explicitly accepted development environment.
4. Validate scanner recovery with the EICAR test signature, then remove the test
   object and confirm ordinary files transition `SCANNING` to ready.
5. Reconcile private quarantined objects according to retention/incident policy.

## Rate or AI quota exhaustion

1. Use the 429 error code to distinguish `RATE_LIMIT_EXCEEDED` from
   `AI_QUOTA_EXCEEDED`; honor `Retry-After`.
2. Inspect tenant/session counters without logging session tokens.
3. Do not restart the process to bypass a limit. Snapshot-backed counters survive
   restart, but are deliberately not coordinated across multiple API processes.
4. Quota reservations use the routed maximum before provider execution and are
   not refunded after provider failure; adjust only through controlled policy.

## Idempotency conflict

1. Retry a timed-out mutation with the identical key and byte-equivalent body.
2. `IDEMPOTENCY_CONFLICT` means that key was already bound to another payload;
   generate a new key only for a genuinely new user intent.
3. Keep `CTF_IDEMPOTENCY_POLICY=required` in deployed environments. `optional`
   and deterministic keyless modes exist only for explicit legacy transitions.
4. Idempotency state is durable with SQLite/PostgreSQL snapshot persistence but
   does not provide multi-process exclusion.

## AI provider degradation

1. Persist user input before any retry.
2. Provider/network failures fail the run safely; do not create retry storms. Invalid JSON/schema gets one schema-aware retry.
3. Use only explicitly configured equivalent-capability model changes. Never downgrade T3 to T1.
4. If no provider/model exists, return `AI_PROVIDER_NOT_CONFIGURED` or `AI_MODEL_NOT_CONFIGURED`; deterministic/manual work remains available.
5. Inspect the tenant-authorized run record and cost ledger. They contain safe errors and versions, never credentials, raw output or chain-of-thought.
6. Compare a recovered model against critical golden cases before changing the tier-to-model map.

For Ollama, inspect authenticated `GET /api/v1/ai/readiness`. If it reports
`AI_PROVIDER_UNREACHABLE`, start the runtime and verify `OLLAMA_BASE_URL`; if a
model is false, pull that exact required model. Do not switch to `fake` as
degradation behavior. Fake mode is an explicit, non-production UI test mode
only. Local T3/T4 remain blocked unless their individual opt-in flags and
validated models are deliberately configured.

## AI configuration rotation

1. Supply `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL_MAP`,
   `AI_PRICING_MAP` and `AI_PRICE_SNAPSHOT_ID` through the deployment secret and
   configuration system; never commit a populated environment file.
2. Verify the base URL is the intended OpenAI-compatible endpoint and restrict
   outbound network policy accordingly.
3. Validate one low-consequence structured run, then a T3 run; confirm model,
   tier, prompt version, usage and price snapshot in the run ledger.
4. Rotate the key without putting it in request bodies, logs, audit events or
   Creation Memory. Revoke the previous key after the smoke checks pass.

## Local Ollama start and recovery

1. Follow `docs/local-ai.md`; the helper provides install guidance but never
   installs Ollama.
2. Native Windows: run `scripts/local-ai.ps1 -Action check`, then `-Action pull`
   for readiness-reported missing T1/T2 models.
3. Compose: run `docker compose --profile local-ai up -d ollama ollama-init`.
   The volume is persistent and no GPU is required by the Compose definition.
4. Verify readiness reports `provider=OLLAMA`, `reachable=true`, and all required
   models true before executing.
5. Keep T3/T4 flags false after recovery unless the exact high-tier model has
   passed critical golden cases. Never remap T3 to a smaller tier to restore
   availability.

## KHAL offline or stale

1. Check `/api/v1/eri/khal/health`; record `status`, `last_success_at`, and `stale`.
2. Verify `KHAL_ENABLED`, `KHAL_BASE_URL`, timeout/pagination limits, and the
   affected CTF tenant's `KHAL_TENANT_MAP` entry. Never print the token or
   credential reference resolution result.
3. Confirm the secret resolver can resolve `KHAL_CREDENTIAL_REFERENCE`; rotate
   at the secret store if needed, without putting credentials in API payloads.
4. Keep CTF functional using responses marked `LAST_VERIFIED_CACHE` or
   manual/document evidence. Treat `stale: true` as historical, not current.
5. Do not infer attribution. Deduplicate delayed measurements on tenant +
   provider + external ID.
6. After recovery, query a narrow metric/time window, verify external tenant and
   entity mappings, compare observed timestamps/units/quality, and reassess
   materiality before broader ingestion.
7. Confirm no event automatically opened a cycle or human gate and no non-GET
   request reached KHAL.

## Suspected tenant-data exposure

1. Disable affected routes/signed URL issuance and preserve evidence.
2. Rotate affected continuation/integration credentials and revoke active signed links.
3. Identify objects, principals, tenants, timestamps and access paths from audit logs.
4. Verify database rows, object keys, caches, search indexes and backups—not only API logs.
5. Correct policy/query scoping and run two-tenant negative tests.
6. Follow legal/contractual notification procedures and record an incident timeline.

## Prompt injection or unsafe model behavior

1. Quarantine the source and capture document/event hash, prompt version, model route and structured output.
2. Reject unauthorized memory operations, nonexistent references and authority changes.
3. Disable the affected prompt/model route if containment requires it.
4. Add a minimized adversarial golden case; test schema, tool allowlist and content boundary.
5. Re-enable only after authority, evidence and genealogy suites pass.

## Backup and restore

- Back up PostgreSQL with point-in-time capability and versioned private object storage on coordinated schedules.
- Record database snapshot time and object version boundary.
- Quarterly restore into an isolated environment, validate checksums and run project/attachment/genealogy integrity checks.
- Test that deleted/expired tenant data is not unintentionally revived into production.

## Release and rollback

1. Validate OpenAPI, prompt registry, golden schema, Compose config and checklists in CI.
2. Apply backward-compatible database migrations before application rollout.
3. Verify readiness, one normal flow, one stale-version conflict and one cross-tenant denial.
4. Roll back application first when schema remains compatible. Never destructively reverse a migration during an incident.
5. Pause and repair if a migration changes immutable decision/genealogy semantics.

## Incident severity

- **SEV-1:** cross-tenant exposure, altered human decision/R0, AI gate confirmation, KHAL actuation, unrecoverable genealogy corruption.
- **SEV-2:** consequential workflow unavailable, attachments inaccessible, systematic evidence misclassification.
- **SEV-3:** degraded AI/KHAL with safe fallback, non-consequential performance regression.

Close incidents only with root cause, impact, timeline, corrective controls, regression test and named owner.

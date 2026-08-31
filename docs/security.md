# CTF Full V1 Security Baseline

## Protected assets

Tenant projects, Creation Memory, immutable human decisions, evidence and genealogy, uploaded documents, anonymous continuation tokens, AI/provider credentials, KHAL read-only credentials, audit records and model/cost telemetry.

## Threat model and controls

| Threat | Required control and verification |
|---|---|
| Cross-tenant object access / IDOR | resolve tenant and project ownership server-side for every endpoint, object-store key and signed URL; negative two-tenant tests |
| Gate or workflow bypass | backend-owned state machine; active `PENDING` gate, allowed choice and expected versions checked in one transaction |
| AI authority escalation | reject model output that confirms human records, selects final objects or mutates state outside allowed operations |
| Prompt injection in uploads/KHAL text | treat external content as untrusted data; isolate instructions; tool allowlist; validate all references and output schemas |
| Malicious upload | extension + MIME + magic-byte + size validation, quarantine, malware scan, sanitized filename, private bucket, no execution |
| Signed URL leakage | short TTL, narrow object/method scope, HTTPS, no secrets in logs or referrers |
| Race/replay | optimistic locking and mandatory idempotency keys for consequential writes; atomic uniqueness constraints |
| Genealogy/evidence fabrication | references must exist, belong to the project and be valid for the exact object version before persistence |
| Secret disclosure | environment/secret manager only; redact logs; never include API/admin credentials in prompts or memory |
| KHAL privilege escalation | V1 credentials read-only; deny write/control/configuration; tenant mapping and egress allowlist |
| Telemetry over-collection | KHAL aggregates raw telemetry; CTF stores only required evidence snapshots and provenance |
| Denial/cost abuse | request/file/token limits, rate limits, queue limits, operation budgets, circuit breakers and per-tenant quotas |
| Audit tampering | append-only records, restricted writer role, timestamp/request/actor correlation, protected retention/export |

## Authorization model

Every request derives a trusted principal: registered user, scoped anonymous session, service integration or operator. Authorization is `(principal, tenant, project, action, object)` and defaults to deny. Anonymous tokens are high-entropy, expire, are hashed at rest and cannot enumerate projects. Operator access is audited and never implied by application membership.

## Human-authority invariants

1. AI may create candidates, never a human confirmation.
2. Human gates 01–19 require an explicit authorized action.
3. Confirmed decisions, values, commitments, roadmaps, R0/R1 and cycle closures are immutable; changes supersede.
4. Non-negotiable conflicts block ordinary GO.
5. Mandatory decision-relevant escalation cannot be downgraded by AI.
6. Garage Alpha ERI cannot actuate external devices.

## Data lifecycle

- Classify project data as private tenant data; it is never global training knowledge by default.
- Encrypt in transit and at rest; production database and object storage use managed keys where available.
- Retention is configurable by data class. Project deletion schedules attachments and derived artifacts consistently.
- Backups inherit encryption, access restrictions and deletion obligations; restoration tests include tenant boundaries.
- Do not persist hidden chain-of-thought. Store concise rationale, evidence references, limitations and alternatives.
- Logs exclude document bodies, prompts containing personal data, credentials and signed URLs.

## Upload pipeline

`receive → stream size limit → inspect type → quarantine → checksum/deduplicate → malware scan → private storage → metadata/audit → READY_FOR_LATER_PROCESSING`

Semantic analysis status is distinct from storage status. Failed scans produce `REJECTED`, safe errors and no usable partial object. Document parsing runs sandboxed with resource limits and cannot initiate network access unless explicitly allowed.

## API baseline

- TLS 1.2+ externally; secure cookies where cookies are used; CSRF protection for cookie-authenticated writes.
- Strict schema, enum, identifier, pagination and content-type validation.
- Stable generic errors with request IDs; no stack traces or raw model errors.
- Security headers and a restrictive CORS allowlist.
- Rate limits by principal, tenant, route and expensive operation.
- `Idempotency-Key` on project creation, input, gate and consequential confirm/close operations.

## Security release gates

Block release for any cross-tenant access, AI-confirmed gate, overwritten human decision/R0, accepted forged reference, KHAL write capability, unresolved critical dependency vulnerability, secret in repository/log output, or normal GO across an unresolved confirmed non-negotiable conflict.

See `tests/security-checklist.md` for executable evidence expectations and `docs/runbooks.md` for response procedures.

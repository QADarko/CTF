# Security Verification Checklist

## Identity and tenant isolation

- [ ] Test registered, anonymous, expired, revoked, integration and operator principals.
- [ ] For every object route, Tenant A cannot read/write/list/infer Tenant B identifiers.
- [ ] Anonymous continuation tokens have sufficient entropy, are hashed at rest, expire and cannot enumerate.
- [ ] Object-store keys and signed URLs enforce the same project authorization as metadata.

## Authority and workflow abuse

- [ ] AI/service calls to all 19 gate decisions are denied.
- [ ] Inactive, already-decided, wrong-stage and stale-version gate attempts are rejected.
- [ ] Race duplicate gate requests produce exactly one decision and transition.
- [ ] Forged HUMAN origin, confirmed value, decision, commitment, roadmap, R1 or cycle closure in model output is rejected.
- [ ] Non-negotiable conflict cannot be bypassed through alternate API route or stale brief.

## Upload and content

- [ ] Test extension/MIME/magic mismatch, polyglot, oversized, archive bomb, macro document, traversal filename and malware fixture.
- [ ] Upload is quarantined until checks pass; rejection leaves no retrievable partial object.
- [ ] Parser sandbox has CPU/memory/time limits and denied-by-default network access.
- [ ] Prompt injection in PDF/DOCX/XLSX and KHAL text cannot alter system policy, call tools or confirm state.
- [ ] Private bucket denies anonymous list/get and signed URLs expire with narrow method scope.

## API and web controls

- [ ] TLS, CORS allowlist, security headers, cookie flags and CSRF controls match deployment authentication.
- [ ] Input schemas reject additional dangerous fields, invalid enums, overlong text and malformed IDs.
- [ ] Rate and cost limits cover login/session, uploads, AI operations, search and provider ingestion.
- [ ] Errors contain stable code/request ID and no stack, SQL, model, secret or internal object key.
- [ ] Idempotency key is principal/route/body-bound and resistant to replay with altered payload.

## Evidence, genealogy and AI

- [ ] Every persisted reference exists in the same tenant/project and expected version.
- [ ] Retrieval cannot cross project boundaries through vector/search filters.
- [ ] Model context excludes secrets, signed URLs, hidden chain-of-thought and unauthorized records.
- [ ] Unsafe fallback cannot lower capability below operation minimum.
- [ ] Adversarial outputs cannot introduce unsupported facts through rendering or memory patches.

## ERI/KHAL

- [ ] Credential permits only documented read endpoints; device control/configuration writes fail.
- [ ] CTF-to-KHAL egress is allowlisted and TLS validated; webhook authentication resists replay.
- [ ] CTF/KHAL tenant mapping is server-enforced.
- [ ] Duplicate, delayed, out-of-order, stale and malformed events are safely handled.
- [ ] Raw telemetry is aggregated outside LLM context; retained snapshots are minimized.
- [ ] Provider outage and stale data do not trigger automatic decisions, cycles or actions.

## Secrets, logs and supply chain

- [ ] Secret scan covers repository and generated artifacts; `.env` is ignored.
- [ ] Logs redact tokens, authorization headers, document bodies, prompts with sensitive data and signed URLs.
- [ ] Container images are pinned by approved version/digest for release and scanned for critical vulnerabilities.
- [ ] Dependencies produce SBOM/provenance; critical vulnerabilities block release or have approved time-bound exception.
- [ ] Database/object backups are encrypted, access-controlled and restoration-tested.

## Release blockers

Any confirmed cross-tenant access, AI authority bypass, mutable human decision/R0, accepted forged genealogy/evidence, leaked secret, public attachment, or KHAL write capability is an unconditional release blocker.

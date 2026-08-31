# CTF Full V1 Architecture

## Scope

Full V1 is a modular monolith around PostgreSQL, private object storage, a REST API, a server-side Orchestrator, and provider-independent AI and External Reality interfaces. The five slices complete one creation cycle:

`R0 → Question → Perception → Evidence → Opportunity → Spark → Idea → Decision → Commitment → Action → Creation → Value → Transformation → R1`

A project is long-lived and may contain multiple immutable creation cycles. `R1` may be the starting reality of cycle 2; it never overwrites `R0`.

## Trust and authority boundaries

| Boundary | Authority |
|---|---|
| Workflow state, versions, transitions, idempotency | deterministic backend |
| Gate decisions, values, commitments, roadmaps, final decisions, cycle closure | authenticated human |
| Structured proposals and assessments | AI, always proposed/derived |
| Facts and measurements | evidence plus provenance, never model confidence alone |
| Binary documents | private object storage; metadata and references in PostgreSQL |
| KHAL | read-only external reality provider in V1; no actuation |

The browser cannot set `current_stage`. AI cannot confirm a gate. A gate transaction atomically validates ownership, active pending gate, expected object versions and allowed decision; records the human decision; applies validated memory operations; changes state; and appends audit events.

## Logical components

- **REST API:** authentication, tenant authorization, idempotency, request validation and stable error contracts.
- **Orchestrator:** loads canonical state, compiles operation context, selects allowed tools/capability, validates structured output and proposes the next route.
- **Rule engine (T0):** gates, state transitions, dependency eligibility, stale-version checks, genealogy references, evidence requirements, mandatory escalation, arithmetic and deduplication.
- **Creation Memory:** versioned structured state separate from conversation history. Confirmed records are immutable or superseded, never silently rewritten.
- **Creation Genealogy:** persisted links created with each object. Explanations may render links but may not invent them.
- **Prompt Registry / Context Compiler:** stable constitution + operation policy + schema precede minimum relevant dynamic context.
- **Model Router:** T0 deterministic; T1 efficient extraction; T2 standard reasoning; T3 critical reasoning; T4 selective independent verification. No vertical slice calls a provider directly.
- **Document Intelligence:** parse once, structure, chunk, index, retrieve and extract scoped evidence with document/page/section provenance.
- **Object storage:** private attachment bucket; authorized retrieval or short-lived signed URLs; no predictable public URLs.
- **ERI:** provider abstraction for manual, document and KHAL reality. KHAL supports V1 OBSERVE and VERIFY only.
- **Audit/telemetry:** workflow, gate, AI provider/model/prompt/methodology, token/cost, attachment and ERI events.

### KHAL provider boundary

`ExternalRealityProvider` exposes only tenant-scoped `assets`, `metrics`,
`measurements`, and readiness operations. `KHALProvider` makes bounded,
paginated GET requests using `KHAL_BASE_URL`; it resolves the bearer token only
at request time through a secret reference and maps the CTF tenant to an
external KHAL tenant before any network call. There are no command, write, or
actuation methods.

KHAL responses are normalized and credential-shaped fields are rejected.
Measurements retain provider/external IDs, observed and received times, units,
quality, and source provenance. Ingestion deduplicates on CTF tenant, provider,
and external ID and explicitly leaves causal attribution unassessed. Last
verified normalized responses may be served during an outage with degraded,
age, and stale metadata; raw upstream payloads and credentials are never cached.

## AI execution boundary

`AIExecutionService` is the only provider-calling boundary. It loads immutable
operation metadata from the YAML Prompt Registry, resolves the operation through
`ModelRouter`, compiles constitution + operation policy + authority rules +
minimum relevant memory/evidence, and enforces route input/output budgets.
Unknown operations fail closed.

Providers implement a small `ModelProvider` protocol. The keyed production
adapter is OpenAI-compatible HTTP. The first-class Ollama adapter needs no key,
uses its OpenAI-compatible `/v1` chat contract, tolerates omitted usage metadata
and older versions that reject `response_format`, and uses native `/api/tags`
only for readiness/model discovery. The deterministic fake is available solely
through explicit `AI_PROVIDER=fake`, identifies itself as non-production, and
returns schema-valid operation fixtures without network calls. No unavailable
provider silently falls back to it.

Tier-to-model, timeout and pricing maps are runtime configuration. Ollama allows
T1/T2 locally; T3/T4 require separate explicit flags after model validation.
Missing providers/models and blocked local tiers fail explicitly, and a T3 route
has no lower-capability fallback. Authenticated readiness reports provider type,
safe reachability, required model availability and limitations without URLs or
secrets.

Responses must be a single JSON object matching the operation's registered JSON
Schema. Invalid JSON/schema receives at most one schema-aware retry. Provider
payloads and hidden reasoning are never persisted. Each attempt group records a
tenant-owned run with provider, model, prompt/methodology versions, outcome,
usage, latency, pricing snapshot, estimated cost, retry count, input-message
reference and safe error. The user input MESSAGE is committed before the
provider is invoked.

All AI output is `PROPOSED` or `CANDIDATE`. The boundary rejects model attempts
to decide a gate or confirm/select/activate Human-owned records. Optional
persistence then uses the same stage, genealogy, evidence and resource
validation as manual writes; Human Decisions and Value Boundaries cannot be
persisted by AI. Manual/deterministic APIs remain available when AI is disabled.

## Slice state and gates

| Slice | Stages | Gates |
|---|---|---|
| VS01 | Reality, Question, Perception | 01 reality; 02 question; 03 perception |
| VS02 | Evidence, Opportunity, Spark, Idea | 04 evidence; 05 opportunities; 06 spark; 07 selected idea |
| VS03 | Assumptions, adversarial, values, decision | 08 assumptions; 09 adversarial; 10 values; 11 human decision |
| VS04 | Commitment, roadmap, execution feedback | 12 commitment; 13 roadmap; 14 re-decision; 15 reaffirmation |
| VS05 | Stakeholders, value, transformation, new reality | 16 stakeholders; 17 value; 18 R1; 19 cycle route |

Controlled backward transitions create a new version and preserve downstream history. REDESIGN returns only as deep as the diagnosed cause requires. NO_GO preserves all learning. VALIDATE_FIRST creates a traceable validation plan.

## Persistence rules

- The current runtime uses one SQLAlchemy JSON snapshot row to preserve the
  proven in-memory aggregate and atomically flush it at repository transaction
  boundaries. Existing normalized mappings remain the intended scale-out seam.
- `CTF_DATABASE_URL` selects persistence; no value means in-memory, while
  Compose always supplies PostgreSQL. Runtime startup initializes missing tables
  and Alembic revisions support managed schema upgrades.
- Every mutable aggregate has an optimistic version.
- Consequential POSTs require `Idempotency-Key`; provider events deduplicate on `(provider, external_event_id)`.
- Raw document binaries, secrets, chain-of-thought and raw telemetry are excluded from Creation Memory.
- Evidence is canonical; context-specific links define exactly what it supports, contradicts, measures or verifies.
- The snapshot repository is single-process. Multiple writers require
  cross-process locking or completion of the normalized repository.
- Attachment metadata and opaque private object keys are persisted in the
  repository; binaries use local filesystem or S3-compatible private storage.

## Local Document Intelligence

Document Intelligence is an offline, provider-free pipeline. The API persists a
`DOCUMENT_JOB` before dispatching work through FastAPI `BackgroundTasks`; the
`DocumentIntelligenceService` is repository/object-store injected so the same
worker boundary can move to an external queue without changing extraction
semantics. Job transitions (`QUEUED → PROCESSING → COMPLETED|FAILED`), results,
counts, progress and safe error codes are committed through repository
transactions. Re-submitting the same attachment/checksum returns the existing
job and does not duplicate derived records.

- PDF uses `pypdf`, DOCX uses `python-docx`, and XLSX uses read-only `openpyxl`;
  TXT and CSV use the Python standard library with strict UTF-8 decoding.
- Existing 20 MiB upload limits remain authoritative. Parsers additionally cap
  extracted text, pages, sheets, rows, columns and Office ZIP expansion/file
  count/compression ratio; encrypted PDFs and unsafe/encrypted Office members
  fail closed.
- Parsers emit text units with available page, sheet, row and section
  provenance. DOCX pagination is not encoded reliably in the file format, so
  heading sections are retained instead of invented page numbers.
- Chunking is deterministic and bounded to 4,000 characters. Chunk IDs and
  checksums derive from attachment checksum, format, location and exact text.
- Document text is never interpreted as an instruction. No LLM is called.
  Deterministic sentence segmentation creates `CANDIDATE_UNCONFIRMED` `CLAIM`
  and `EVIDENCE` records linked to an `EVIDENCE_SOURCE`; each record retains
  attachment/checksum/chunk/location provenance and requires later human
  confirmation.
- Parsed metadata and paginated chunks are available only through the
  tenant/session-authorized project route.

`BackgroundTasks` is suitable for the single-process local topology but is not
a durable distributed queue. A process interruption can leave a durable job in
`QUEUED` or `PROCESSING`; re-submitting that attachment safely resumes it.
Multi-process deployment should bind the existing service seam to a durable
queue and use the normalized/locked repository described above.

## Reliability and degradation

- Persist user input before AI calls.
- Permit one schema-aware retry; otherwise return a recoverable error without exposing model internals.
- Never lower a T3 operation to T1 because of availability or budget.
- KHAL outage leaves CTF usable: show timestamped last verified data or request manual/document evidence.
- Stale KHAL data remains stale; measurement never implies attribution.
- PostgreSQL and object storage backups are coordinated through project/attachment identifiers and retention policy.

## Runtime topology

Local Compose supplies PostgreSQL and MinIO. Optional Nginx placeholders reserve API and web ports without creating conflicting application sources. Production should terminate TLS at an ingress, use managed secrets and encrypted managed storage, isolate private networks, run malware scanning, and export logs/metrics to the deployment observability system.

## Quality attributes

- **Integrity:** zero AI-confirmed human gates; deterministic genealogy and version checks.
- **Privacy:** tenant isolation on every project, file and ERI request.
- **Availability:** core workflow remains operable without AI retry storms or KHAL.
- **Performance:** normal AI input under 16K tokens; API reads p95 under 500 ms excluding AI; asynchronous large-document analysis.
- **Economics:** measure cost per creation cycle and meaningful execution event, not per message.

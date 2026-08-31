# Architecture Decision Records

## ADR-001: Modular monolith, PostgreSQL/JSONB and private object storage

- **Status:** Accepted for Full V1
- **Decision:** Build one server-side application boundary with PostgreSQL relational records for authority/audit/versioning, JSONB for evolving CTF structures, and MinIO/S3-compatible private storage for binaries.
- **Why:** Full V1 needs transactional gates and deterministic traceability more than distributed scaling. A graph database, event bus and microservices add failure modes without V1 value.
- **Consequences:** Application migrations own domain schema; binaries are never embedded in Creation Memory; async document processing may use workers while retaining one logical domain.

## ADR-002: Deterministic orchestration and human authority

- **Status:** Accepted
- **Decision:** Backend rule logic owns state, eligibility, references and mandatory escalation. AI emits schema-validated proposals. Human gates 01–19 are explicit, server-enforced and transactional.
- **Why:** Model output is probabilistic and cannot be the authority for consequential choices or immutable records.
- **Consequences:** Every AI operation has allowed actions; gate decisions require actor and version context; stale or unauthorized model output is rejected rather than repaired silently.

## ADR-003: Persisted genealogy, canonical evidence and immutable versions

- **Status:** Accepted
- **Decision:** Create genealogy links at object creation, reuse canonical Evidence with scoped links, and supersede confirmed records rather than overwriting.
- **Why:** Post-hoc model explanations cannot guarantee provenance. Multi-cycle learning requires exact versions from R0 through R1.
- **Consequences:** Broken references block completion; trace APIs traverse persisted links; R1 may seed a new cycle but R0 remains immutable.

## ADR-004: Minimum Sufficient Intelligence

- **Status:** Accepted
- **Decision:** All AI work routes by capability (T1 efficient, T2 standard, T3 critical, selective T4 verification), with T0 deterministic work avoiding LLM calls. Context is operation-specific and budgeted.
- **Why:** Quality and authority constraints must hold while controlling cost, latency and context pollution.
- **Consequences:** Vertical slices are provider-independent; no unsafe capability downgrade; token/model/cost telemetry is mandatory; model promotion requires golden tests.

## ADR-005: ERI abstraction and read-only KHAL V1

- **Status:** Accepted
- **Decision:** Integrate external reality through `ExternalRealityProvider`; KHAL is the first machine provider and supports OBSERVE/VERIFY only. CTF remains usable offline.
- **Why:** CTF reasons about creation while KHAL measures reality. Hard coupling or actuation would collapse safety and product boundaries.
- **Consequences:** Scoped read-only credentials, raw-telemetry exclusion, provider event deduplication, explicit staleness and no causal claim from measurement alone.

## ADR-006: REST contract and asynchronous heavy processing

- **Status:** Accepted
- **Decision:** Expose versioned REST/JSON contracts; use `202 Accepted` jobs for large document analysis and other long operations.
- **Why:** A stable public boundary supports independent web/backend work and avoids request timeouts.
- **Consequences:** OpenAPI is authoritative at the boundary; errors use stable codes and request IDs; jobs must expose status, retry safety and tenant authorization.

## Change process

Superseding an accepted decision requires a new ADR that names the replaced decision, migration impact, security impact and golden scenarios that demonstrate equivalent or stronger invariants.

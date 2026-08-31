# Performance and Resilience Checklist

All results record dataset, concurrency, environment, build, percentile distribution and error rate. Exclude placeholders from product benchmarks.

## Service objectives for Alpha

| Workload | Initial objective |
|---|---|
| Non-AI API read/write | p95 < 500 ms / 1 s |
| Gate transaction | p95 < 1 s, exactly-once result |
| Attachment metadata/list | p95 < 500 ms at 1,000 attachments/project |
| Upload acceptance | stream without loading full file; 25 MiB default limit |
| Large document analysis | asynchronous `202`; bounded worker memory |
| Normal AI context | median <6K, p90 <12K, ≥95% <16K input tokens |
| AI output | median <800, p90 <2K output tokens |
| Structured model response | ≥95% valid after at most one retry |
| KHAL event ingestion | p95 <1 s excluding downstream AI; idempotent |

## Data and concurrency

- [ ] Gate race at 20 concurrent identical/conflicting decisions yields one transition and no partial audit.
- [ ] Idempotent retry storm returns one logical result without duplicate AI run, event or attachment.
- [ ] Optimistic-lock conflicts remain bounded and do not deadlock.
- [ ] Genealogy traversal is measured at 10 cycles / 10,000 links and uses bounded queries.
- [ ] Evidence/search queries enforce tenant filters without full scans.
- [ ] Connection pool saturation degrades safely and recovers.

## Documents and object storage

- [ ] 25 MiB upload streams with stable process memory and checksum.
- [ ] 150-page document parses/chunks once; later calls retrieve 2K–6K relevant tokens instead of full resend.
- [ ] Concurrent upload/scan failures leave no usable partial metadata/object.
- [ ] Signed retrieval supports backpressure and does not proxy large binaries through app memory unless required.

## AI routing and economics

- [ ] T1/T2/T3 operation distributions and escalation rates are reported.
- [ ] Routine calls avoid escalation ≥90%; retries and schema failures are separately measured.
- [ ] Stable prompt-prefix cache hit ratio and cached input tokens are captured.
- [ ] No T3 downgrade under injected timeout/rate-limit/cost pressure.
- [ ] Cost ledger reconciles provider-reported usage by run, slice, gate, cycle and meaningful execution event.
- [ ] Useful-context ratio identifies retrieval waste; regression threshold is defined after baseline.

## Resilience

- [ ] Stop PostgreSQL during a gate request: no success is acknowledged without committed state; recovery is reconcilable.
- [ ] Stop MinIO during upload: no false `STORED`; retry/reconciliation is safe.
- [ ] Inject AI timeout, rate limit, invalid JSON and provider outage: bounded retry, preserved input, safe error.
- [ ] Take KHAL offline and deliver delayed/out-of-order events after recovery: staleness and `observed_at` semantics hold.
- [ ] Worker crash during document analysis resumes or safely restarts without duplicate evidence.
- [ ] Backup restore recovers matching project, attachment and genealogy boundaries.

## Longitudinal and multi-cycle

- [ ] A 12-month simulated project does not resend full history each operation.
- [ ] Ten creation cycles preserve immutable snapshots with bounded workspace/context compilation.
- [ ] Execution events are paginated/archived without losing decision-relevant trace.
- [ ] Replan changes only affected branch and does not regenerate an entire roadmap for local events.

## Capacity report

Before pilot, publish measured single-instance safe limits for concurrent users, AI jobs, document jobs, KHAL event rate, database size, object storage and monthly cost. These are capacity observations, not guarantees; set alerts below saturation and rerun after material schema/model changes.

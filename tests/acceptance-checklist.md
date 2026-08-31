# Integrated Acceptance Checklist

Record a CI/test/pilot evidence link and owner beside every checked item. Full V1 is closed only after functional, technical and human validation.

## Infrastructure and API

- [ ] Compose config resolves with secrets supplied; PostgreSQL and MinIO become healthy.
- [ ] `minio-init` creates one private bucket and anonymous access is disabled.
- [ ] Application migrations—not bootstrap SQL—own domain tables and can start from an empty database.
- [ ] OpenAPI validates and implementation contract tests match methods, status codes and errors.
- [ ] Readiness fails when required persistence is unavailable; liveness does not cause restart loops.

## Cross-cutting invariants

- [ ] All project, attachment, evidence, trace and ERI accesses enforce tenant ownership.
- [ ] Gates 01–19 reject AI/service principals and non-active, decided, stale or invalid choices.
- [ ] Gate decision, subject confirmation, memory patch, transition and audit append are atomic.
- [ ] Duplicate consequential requests return the original result; two-tab stale writes return `STATE_CONFLICT`.
- [ ] Confirmed R0, decisions, values, roadmaps, R1 and cycle closures are immutable/superseded.
- [ ] Invalid/non-project evidence and genealogy references are rejected.
- [ ] AI runs record operation, provider, model, prompt/methodology version, capability, effort, status, latency and available token/cost usage.
- [ ] One schema-aware retry maximum; user input survives model failure.

## VS01

- [ ] Creation, Funding and Document entries create the same project root; anonymous resume/expiry is safe.
- [ ] Reality adapts for simple, ambiguous, idea-first and systemic cases without premature solutions.
- [ ] Questions are limited to three; recommendation does not override custom/edited human selection.
- [ ] Unsupported perceptions are hypotheses; reject/partial paths do not become confirmed facts.
- [ ] Upload validates type/size/magic bytes, malware, ownership and audit; UI makes no false semantic-analysis claim.

## VS02

- [ ] Evidence items retain source and location; conflicting evidence remains visible.
- [ ] Opportunities are traceable spaces, not solutions; orphan opportunities fail.
- [ ] USER/CTF/CO_CREATED Spark origin survives selection and combination.
- [ ] Idea Blueprint preserves unknown budget, TRL, market and regulatory fields.
- [ ] Selected Idea has deterministic R0→Question→Perception→Evidence→Opportunity→Spark→Idea genealogy.

## VS03

- [ ] Kill assumptions are material and human-confirmed; minor risks are not inflated.
- [ ] Red Team is specific, evidence-aware, fair and logically independent.
- [ ] Human values remain human-owned; unresolved non-negotiable conflict blocks ordinary GO.
- [ ] Decision Brief binds exact Idea version and introduces no new facts.
- [ ] CTF recommendation and human decision are separate; divergence and rationale persist.
- [ ] VALIDATE_FIRST creates a specific plan; REDESIGN routes minimally; NO_GO/HOLD preserve learning.

## VS04

- [ ] Commitment binds exact immutable decision and does not invent owner/resources.
- [ ] Outcomes are observable states; milestones have success criteria; actions have WHY and trace.
- [ ] Circular hard dependencies fail; blocked actions are ineligible for NBA.
- [ ] Roadmap remains inactive before Gate 13 and replans create minimal immutable diffs.
- [ ] Required evidence gates VERIFIED; submission does not equal approval.
- [ ] Invalidated kill assumption forces decision-relevant route despite lower AI classification.
- [ ] Commitment drift uses observable state and no character judgments.
- [ ] Creation Record proves existence and does not claim Value.

## VS05 and multi-cycle

- [ ] Stakeholder map includes potential harm and is human-confirmed.
- [ ] Hypotheses, baselines, metrics and observations preserve status/provenance and time series.
- [ ] Creation/adoption/outcome/value/impact/transformation remain distinct.
- [ ] Mixed Value retains negative effects and distribution; attribution remains conservative.
- [ ] Impact has complete pathway; transformation is not inferred from digitization or one KPI.
- [ ] R1 includes improvement, deterioration, unknown and not-comparable dimensions; R0 is unchanged.
- [ ] Gate 19 alone controls close/adapt/next; cycle 2 starts from immutable R1 with separate genealogy.

## AI routing and KHAL

- [ ] All slice operations resolve through registry/router; no provider hard-coding.
- [ ] T0 avoids unnecessary model calls; T3 cannot fall to T1; T4 is selective.
- [ ] Context compiler excludes irrelevant conversation, raw documents, secrets and raw KHAL telemetry.
- [ ] KHAL credentials are read-only and tenant-scoped; write/control calls fail.
- [ ] Events deduplicate on provider/external ID and use `observed_at`.
- [ ] KHAL outage presents staleness and alternatives without disabling core CTF.
- [ ] Measurement can become scoped Evidence but never automatic attribution.

## Golden and human validation

- [ ] Every scenario in `golden/scenarios.yaml` passes required and forbidden assertions.
- [ ] Critical golden cases gate model/prompt promotion and provider substitution.
- [ ] Slice KPI/stop criteria are measured on the plan’s required pilot cohorts.
- [ ] Any absolute-fail authority, overwrite, tenant or genealogy result blocks release regardless of average score.

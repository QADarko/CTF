# CTF V1 External Pilot Validation

## Status

Not executed. External pilot acceptance requires recruited participants, observed
sessions, independent reviewers, and longitudinal evidence. Automated tests and
golden scenarios are readiness evidence, not substitutes for human validation.

## Entry criteria

- All automated backend, state-machine, security, genealogy, and frontend checks pass.
- The deployed environment uses PostgreSQL and private object storage.
- Monitoring, consent, retention, incident response, and participant support are active.
- Pilot datasets contain no production secrets or unconsented personal information.

## Cohorts

1. VS01: 20–30 participants completing entry through Perception.
2. VS02–VS04: at least 20 deeper cases, including evidence-heavy, NO-GO,
   REDESIGN, material-event, and commitment-drift paths.
3. VS03: independent blinded review comparing CTF decision integrity with the
   agreed baseline.
4. VS05: at least 24 completed or historically reconstructable creation cases,
   supplemented by live longitudinal follow-up.
5. ERI/KHAL: one controlled read-only closed-loop proof plus an offline/degraded run.

## Protocol

For every session, record consent, scenario, entry family, stage timestamps,
backtracks, gate decisions, errors, assistance requests, model route/cost,
participant ratings, and facilitator observations. Never infer user intent,
values, or satisfaction from clickstream data.

Run the slices in dependency order:

1. Validate recognition and correction of R0, Question, and Perception.
2. Validate evidence provenance, opportunity grounding, Spark usefulness, and
   Idea genealogy.
3. Validate assumption discovery, adversarial independence, human-owned value
   boundaries, and decision traceability.
4. Validate commitment clarity, evidence-based action completion, NBA usefulness,
   materiality escalation, and minimal-change replanning.
5. Validate stakeholder value, negative effects, attribution restraint,
   transformation classification, R1, and cycle closure.

After each cohort, classify findings as release-blocking, material, or local.
Release-blocking issues stop subsequent external exposure until corrected and
retested. Material findings require an explicit owner and disposition.

## Required acceptance evidence

- Server logs demonstrate that all Human Gates were enforced.
- No illegal state transitions, AI-authored human decisions, invented evidence,
  orphan genealogy, tenant crossover, or R0 overwrite occurred.
- Structured AI output, provenance, traceability, and human-rating thresholds
  meet the corresponding slice criteria in the source specification.
- Independent reviewers can reproduce the source chain for consequential outputs.
- Cost-per-cycle and latency stay within the approved operational budget.
- Negative and mixed outcomes are retained rather than summarized away.

## Report template

- Deployment/version:
- Dates and facilitators:
- Cohort and sample:
- Scenarios completed:
- Quantitative results:
- Qualitative findings:
- Safety/security incidents:
- Genealogy exceptions:
- Model quality and cost:
- Accessibility findings:
- Release blockers:
- Material actions and owners:
- Approved waivers:
- Go/no-go decision and human approvers:

## Release rule

The software is pilot-ready when automated release checks pass. It is validated
for release only after the completed report is reviewed and signed by the
designated human authorities. An empty template or simulated result must never
be represented as a completed external pilot.

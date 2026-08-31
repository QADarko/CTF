# Requirements Traceability Matrix

Status values: `PLANNED`, `IMPLEMENTED`, `VERIFIED`, `BLOCKED`. These infrastructure/documentation assets start at `PLANNED`; implementation teams update evidence links, never requirements text.

| ID | Requirement / invariant | Source scope | Contract or artifact | Verification evidence | Status |
|---|---|---|---|---|---|
| CORE-01 | Backend owns stage and transitions | VS01–05 | OpenAPI workspace/gates; CAP-CORE-01 | `test_full_lifecycle.py::test_complete_r0_to_r1_lifecycle_exercises_all_human_gates` | VERIFIED |
| CORE-02 | AI cannot decide any of gates 01–19 | VS01–05 | prompt registry; CAP-CORE-02 | `test_common_and_gates.py::test_first_three_human_gates_and_ai_authority`; AI authority tests | VERIFIED |
| CORE-03 | Confirmed records are immutable/superseded | VS01–05 | architecture; CAP-CORE-06 | R0 immutability is directly tested; all resource kinds are not | IMPLEMENTED |
| CORE-04 | Genealogy is persisted, never post-hoc invented | VS02–05 | CreationGraph; CAP-CORE-07 | `test_vs01_vs02.py::test_evidence_opportunity_genealogy_and_document_job` | VERIFIED |
| CORE-05 | Evidence preserves source and exact scope | VS02–05 | architecture; CAP-VS02-02 | `test_document_intelligence.py::test_docx_pipeline_preserves_section_and_treats_instructions_as_text`; XLSX/CSV provenance test | VERIFIED |
| CORE-06 | Fact, inference, assumption and unknown remain distinct | all | prompt constitution | hallucination suite | PLANNED |
| CORE-07 | Consequential writes are atomic/idempotent | all | OpenAPI headers; CAP-CORE-04 | project idempotency and transaction rollback tests; route-wide coverage remains partial | IMPLEMENTED |
| VS01-01 | Anonymous multi-entry project creation | VS01 | `/sessions/anonymous`, `/projects`; CAP-VS01-01 | creation and full-lifecycle tests | VERIFIED |
| VS01-02 | Secure PDF/DOCX/XLSX storage without false analysis | VS01 | attachment API; CAP-VS01-02 | `test_vs01_vs02.py::test_attachment_metadata_security_and_no_false_analysis`; document parser failure/auth tests | VERIFIED |
| VS01-03 | Reality uses adaptive minimum questions | VS01 | REALITY prompt | ambiguous/simple/system scenarios | PLANNED |
| VS01-04 | Max three neutral questions; human selects | VS01 | QUESTION prompt; Gate 02 | override/custom question cases | PLANNED |
| VS01-05 | Perception labels unsupported hypotheses | VS01 | PERCEPTION prompt | rejection/inference cases | PLANNED |
| VS02-01 | Documents are sources; extracted items are evidence | VS02 | Document Intelligence; CAP-DOC-01, CAP-DOC-05 | `apps/api/tests/test_document_intelligence.py` (DOCX/XLSX/TXT/CSV/PDF, candidate provenance, dedupe, safe failure, SQLite restart) | VERIFIED |
| VS02-02 | Opportunity remains broader than solution | VS02 | OPPORTUNITY prompt | premature-solution case | PLANNED |
| VS02-03 | Spark origin and human selection preserved | VS02 | SPARK prompt; Gate 06 | USER/CTF/CO_CREATED tests | PLANNED |
| VS02-04 | Idea Blueprint unknowns are not fabricated | VS02 | IDEA + logic prompts | budget/TRL/market cases | PLANNED |
| VS03-01 | Kill assumptions are materially calibrated | VS03 | assumption prompts; Gate 08 | minor-cost/kill cases | PLANNED |
| VS03-02 | Red Team is specific, independent and evidence-aware | VS03 | red-team/premortem prompts | generic/fairness tests | PLANNED |
| VS03-03 | Human-owned non-negotiables block ordinary GO on conflict | VS03 | values prompt; CAP-VS03-06 | `test_vs03_vs05.py::test_value_boundary_conflict_blocks_go` | VERIFIED |
| VS03-04 | Recommendation and immutable human decision remain separate | VS03 | decision prompts; CAP-VS03-07 | full lifecycle and AI authority tests | VERIFIED |
| VS03-05 | NO_GO, REDESIGN, HOLD and VALIDATE_FIRST preserve learning | VS03 | router prompts | special path golden cases | PLANNED |
| VS04-01 | Commitment and roadmap require Gates 12/13 | VS04 | prompts and gate contract | AI activation rejection | PLANNED |
| VS04-02 | Outcomes are states; actions have WHY | VS04 | outcome/action prompts | activity/orphan-action cases | PLANNED |
| VS04-03 | No VERIFIED without required evidence | VS04 | rule engine; CAP-VS04-05 | `test_vs03_vs05.py::test_action_verification_requires_evidence_and_nba_filters_dependencies` | VERIFIED |
| VS04-04 | NBA filters deterministically before reasoning | VS04 | NBA policy; CAP-VS04-06 | blocked/dependency cases in `test_vs03_vs05.py` | VERIFIED |
| VS04-05 | Mandatory decision-relevant escalation wins | VS04 | impact policies; CAP-VS04-07 | `test_vs03_vs05.py::test_materiality_mandatory_escalation_cannot_be_downgraded` | VERIFIED |
| VS04-06 | Replan is minimal and versioned | VS04 | REPLAN prompt | small-delay/stale roadmap cases | PLANNED |
| VS05-01 | Creation, adoption, value, impact and transformation differ | VS05 | common prompt policy | no-value/high-adoption cases | PLANNED |
| VS05-02 | Baselines and attribution are not invented | VS05 | metric/attribution prompts | unknown/correlation cases | PLANNED |
| VS05-03 | Negative effects and distribution remain visible | VS05 | negative/distribution; CAP-VS05-04 | value invariant test preserves negative effects | VERIFIED |
| VS05-04 | Impact requires a supported pathway | VS05 | impact prompt | broken-link case | PLANNED |
| VS05-05 | R1 includes deterioration/unknowns and cannot overwrite R0 | VS05 | R1; CAP-VS05-06, CAP-VS05-07 | R0 immutability verified; full deterioration/unknown coverage remains partial | IMPLEMENTED |
| VS05-06 | Gate 19 controls close/adapt/next cycle | VS05 | cycle reviewer; CAP-VS05-08 | full lifecycle multi-cycle scenario | VERIFIED |
| AI-01 | Every operation routes by capability, never provider hard-code | horizontal AI | `ai_runtime.py`; CAP-AI-01, CAP-AI-03 | `test_ai_runtime.py::test_prompt_registry_loads_and_rejects_unknown_operation`; routing escalation test | VERIFIED |
| AI-02 | T3 never silently falls to T1 | horizontal AI | CAP-AI-04 | `test_ai_runtime.py::test_t3_never_uses_t1_model` | VERIFIED |
| AI-03 | Model/prompt/methodology/token/cost provenance recorded | horizontal AI | CAP-AI-06 | `test_ai_runtime.py::test_structured_success_records_complete_ledger`; SQLite restart suite | VERIFIED |
| AI-04 | Normal context target <16K and one schema retry | horizontal AI | CAP-AI-05 | invalid JSON, retry exhaustion and budget tests in `test_ai_runtime.py` | VERIFIED |
| AI-05 | Local Ollama is explicit, keyless, observable and fails safely without fallback | horizontal AI | CAP-AI-07, CAP-AI-08 | Ollama protocol/readiness/missing-runtime/no-fallback tests in `test_ai_runtime.py` | VERIFIED |
| AI-06 | Local T3/T4 require explicit opt-in and T3 never downgrades | horizontal AI | local capability policy; architecture | local tier block/explicit T3 model tests in `test_ai_runtime.py` | VERIFIED |
| AI-07 | Deterministic AI fixtures are explicit and non-production | horizontal AI | fake env preset; readiness contract | fake schema-valid operation fixture test in `test_ai_runtime.py` | VERIFIED |
| ERI-01 | KHAL is read-only OBSERVE/VERIFY; no actuation | ERI | `ExternalRealityProvider`, `KHALProvider`; CAP-ERI-03 | `test_khal_provider.py::test_metrics_and_measurements_are_normalized_read_only`; KHAL connection authority test | VERIFIED |
| ERI-02 | Events deduplicate and preserve observed time/provenance | ERI | `KHALProvider`, RealityEvent; CAP-ERI-04 | `test_khal_provider.py::test_enabled_endpoint_calls_provider_and_ingestion_deduplicates`; existing attribution-boundary test | VERIFIED |
| ERI-03 | Raw telemetry never enters LLM context | ERI | architecture/security | context capture inspection | PLANNED |
| ERI-04 | KHAL offline does not block CTF | ERI | health/readiness, verified normalized cache, runbook | KHAL timeout/offline/stale cache tests; offline golden case | VERIFIED |
| ERI-05 | Measurement does not imply causal attribution | ERI/VS05 | CAP-ERI-05 | KHAL ingestion and ERI attribution-boundary tests | VERIFIED |
| ERI-06 | KHAL credentials remain server-side and tenant mapping fails closed | ERI/security | environment secret resolver, tenant map | KHAL tenant, payload rejection, response rejection, and no-secret-leakage tests | VERIFIED |

## Evidence convention

Each verified row should link to a stable CI run, test case ID, security report or signed pilot result. Human KPI evidence records cohort, methodology, sample size and date. A passing unit test cannot substitute for required human validation.

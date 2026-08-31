# CTF AI Golden Evaluation

This corpus is separate from `golden/`, which remains the deterministic software suite.

## Modes

- **CI / structural:** `python -m evals.ctf_ai.runner --provider structural`
- **Local model:** `--provider ollama --tier T2`
- **Candidate provider:** configured external provider
- **Human review:** selected critical outputs only

`FakeProvider` may prove orchestration and schema contracts. It must never produce a semantic model-quality score.

Model capability is earned. A model may be `APPROVED` for T1/T2 and `NOT_APPROVED` for T3/T4.

## Thresholds

- At least 100 scenarios
- Every critical operation represented
- Structural pass required in CI
- Semantic pass/fail is a product approval, not a PR gate

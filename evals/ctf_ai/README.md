# CTF AI Golden Evaluation

This corpus is separate from `golden/`, which remains the deterministic software suite.

Evaluation of model intelligence always runs through `AIExecutionService` (context compiler, consequentiality, routing, and CTF guards). The provider is never called with evaluator expectations.

## Modes

- **CI / structural:** `python -m evals.ctf_ai.runner --provider structural`
- **Orchestration only:** `--provider fake` (`semantic_evaluation: NOT_APPLICABLE`; T1–T3 `NOT_CERTIFIED`)
- **Local model:** `--provider ollama --model qwen2.5:7b`
- **External provider:** `--provider external --model MODEL_ID`
- **Human review:** T3 artifacts are written under `evals/ctf_ai/results/human_review/` with empty reviewer fields

## CLI

```
python -m evals.ctf_ai.runner --provider ollama --model qwen2.5:7b
python -m evals.ctf_ai.runner --provider ollama --model qwen2.5:7b --operation ATTRIBUTION
python -m evals.ctf_ai.runner --provider ollama --model qwen2.5:7b --tier T3
python -m evals.ctf_ai.runner --provider ollama --model qwen2.5:7b --scenario AI-ADV-ATTRIBUTION-TRAP
python -m evals.ctf_ai.runner --provider ollama --model qwen2.5:7b --limit 20
python -m evals.ctf_ai.runner --provider ollama --model qwen2.5:7b --output evals/ctf_ai/results/test.json
```

`FakeProvider` may prove orchestration and schema contracts. It must never produce a semantic model-quality score.

Model capability is earned. A model may be `APPROVED` for `IDEA_BLUEPRINT` and `NOT_APPROVED` for `ATTRIBUTION`. T4 remains `NOT_EVALUATED`.

## Thresholds

- 100–150 meaningful scenarios, including distinct case types for every critical operation
- Structural pass required in CI
- Semantic pass/fail is a product approval, not a PR gate
- Critical safety failure blocks T3 regardless of average score

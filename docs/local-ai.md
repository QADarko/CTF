# Local AI

CTF uses one explicit provider selection. It never chooses the deterministic
fake when Ollama or another provider is unavailable. Check runtime state through
authenticated `GET /api/v1/ai/readiness`; the response contains provider type,
reachability, required model availability, allowed tiers and safe limitations,
but no keys or credential-bearing URLs.

## Zero-install fake mode

This mode exercises the complete AI API and UI with schema-valid,
operation-specific fixtures. It performs no reasoning and is never a production
provider.

PowerShell, before starting the API:

```powershell
Get-Content .env.fake-ai.example | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') { Set-Item "env:$($matches[1])" $matches[2] }
}
python -m uvicorn apps.api.app.main:app --reload --port 8080
```

For Compose, copy the `AI_PROVIDER` and `AI_MODEL_MAP` values from that preset
into `.env`, then run `docker compose up --build`. The API reports
`non_production: true`.

## Native Windows Ollama mode

Ollama is not bundled or automatically installed. View safe installation
guidance:

```powershell
.\scripts\local-ai.ps1 -Action install-guidance
```

After manually installing Ollama:

```powershell
.\scripts\local-ai.ps1 -Action start
.\scripts\local-ai.ps1 -Action pull
.\scripts\local-ai.ps1 -Action check
Get-Content .env.local-ai.example | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') { Set-Item "env:$($matches[1])" $matches[2] }
}
python -m uvicorn apps.api.app.main:app --reload --port 8080
.\scripts\local-ai.ps1 -Action test
```

The API uses Ollama's OpenAI-compatible `/v1/chat/completions` endpoint. Older
versions that reject `response_format` receive one protocol retry without that
field. CTF still validates the registered JSON schema and allows at most one
schema retry. If usage metadata is absent, token counts are conservative local
estimates.

## Compose Ollama mode

Set `AI_PROVIDER=ollama` and `OLLAMA_BASE_URL=http://ollama:11434` in `.env`,
then run:

```powershell
docker compose --profile local-ai up --build
```

The optional CPU-compatible service uses a persistent `ollama-data` volume and
does not request a GPU. `ollama-init` pulls the configured T1 and T2 models. To
operate only the local runtime:

```powershell
.\scripts\local-ai.ps1 -Action start -Mode compose
.\scripts\local-ai.ps1 -Action check -Mode compose
```

## Models, hardware, and high tiers

Defaults are `qwen2.5:3b` for T1 and `qwen2.5:7b` for T2. Override
`OLLAMA_MODEL_T1`, `OLLAMA_MODEL_T2`, or `OLLAMA_MODEL_MAP` when RAM, latency,
language, or model availability requires another choice. Small-memory systems
should start with one 3B-class quantized model for both T1 and T2; more capable
machines can select a validated 7B-class or larger model. Model quality and
memory use vary by quantization and context size, so validate representative
CTF prompts on the actual host.

Local T1 and T2 are enabled. T3 and T4 are denied by default because model
availability is not equivalent to critical-reasoning or independent-verification
quality. Enable `AI_LOCAL_ALLOW_T3=true` or `AI_LOCAL_ALLOW_T4=true` only after
evaluating the exact configured model. A T3 route is never downgraded to T2/T1;
it fails closed if blocked or missing.

Ollama failure returns `AI_PROVIDER_UNREACHABLE` with start/configuration
guidance. Pull missing models named by readiness. Manual CTF workflows remain
available throughout.

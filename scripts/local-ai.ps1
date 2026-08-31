[CmdletBinding()]
param(
    [ValidateSet("check", "install-guidance", "start", "pull", "test")]
    [string]$Action = "check",
    [ValidateSet("native", "compose")]
    [string]$Mode = "native",
    [string[]]$Models = @("qwen2.5:3b", "qwen2.5:7b"),
    [string]$OllamaUrl = "http://localhost:11434",
    [string]$ApiUrl = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"

function Test-OllamaCommand {
    return $null -ne (Get-Command "ollama" -ErrorAction SilentlyContinue)
}

function Show-InstallGuidance {
    Write-Host "Ollama is not installed or is not on PATH."
    Write-Host "Install it manually from https://ollama.com/download/windows"
    Write-Host "Optional manual command: winget install --id Ollama.Ollama"
    Write-Host "This helper intentionally does not install software."
}

switch ($Action) {
    "install-guidance" {
        Show-InstallGuidance
    }
    "check" {
        if ($Mode -eq "native" -and -not (Test-OllamaCommand)) {
            Show-InstallGuidance
            exit 1
        }
        try {
            $tags = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 5
            Write-Host "Ollama is reachable at the configured URL."
            $tags.models | ForEach-Object { Write-Host "  $($_.name)" }
        }
        catch {
            Write-Host "Ollama is not reachable. Start it, then verify the configured URL."
            exit 1
        }
    }
    "start" {
        if ($Mode -eq "compose") {
            docker compose --profile local-ai up -d ollama ollama-init
        }
        else {
            if (-not (Test-OllamaCommand)) {
                Show-InstallGuidance
                exit 1
            }
            Start-Process -FilePath "ollama" -ArgumentList "serve"
            Write-Host "Ollama start requested. Run this script with -Action check to verify."
        }
    }
    "pull" {
        if ($Mode -eq "compose") {
            docker compose --profile local-ai run --rm `
                -e OLLAMA_HOST=http://ollama:11434 ollama-init
        }
        else {
            if (-not (Test-OllamaCommand)) {
                Show-InstallGuidance
                exit 1
            }
            foreach ($Model in $Models) {
                ollama pull $Model
            }
        }
    }
    "test" {
        $tags = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 10
        Write-Host "Ollama models: $($tags.models.Count)"
        $session = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/v1/sessions/anonymous" `
            -ContentType "application/json" -Body '{"tenant_id":"local-ai-smoke"}'
        $headers = @{"X-Session-Token" = $session.token}
        $readiness = Invoke-RestMethod -Uri "$ApiUrl/api/v1/ai/readiness" -Headers $headers
        $readiness | ConvertTo-Json -Depth 6
        if (-not $readiness.configured -or -not $readiness.reachable) {
            exit 1
        }
    }
}

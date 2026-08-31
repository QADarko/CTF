from __future__ import annotations

import json

import httpx
import pytest

from apps.api.app.horizontal import ai_execution as api_ai_execution
from apps.api.app.slices import ai_execution as generator_ai_execution
from packages.ctf_domain.ai_runtime import (
    AIExecutionService,
    FakeProvider,
    OllamaProvider,
    PromptRegistry,
    ProviderResult,
    RuntimeConfig,
)
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.model_router import ModelRouter, Route
from packages.ctf_domain.repository import InMemoryRepository
from packages.ctf_domain.service import CTFService


def project_in(repo: InMemoryRepository, tenant: str = "tenant-a"):
    session = repo.create_session(tenant)
    return repo.create_project(session, "CREATION", "PROBLEM", "input", {}), session


def runtime(repo, responses, *, config=None, router=None):
    return AIExecutionService(
        repo,
        FakeProvider(responses),
        registry=PromptRegistry(),
        router=router,
        config=config
        or RuntimeConfig(
            {"T1": "small", "T2": "standard", "T3": "critical", "T4": "verify"},
            {"standard": {"input_per_mtok": "1", "output_per_mtok": "2"}},
            "prices-v1",
        ),
    )


def valid_output(**item):
    return json.dumps(
        {
            "status": "PROPOSED",
            "items": [item],
            "summary": "safe",
            "grounding": {
                "evidence_refs": [],
                "memory_refs": [],
                "assumptions": [],
                "unknowns": [],
                "limitations": [],
                "confidence_class": "INSUFFICIENT_EVIDENCE",
            },
        }
    )


def test_prompt_registry_loads_and_rejects_unknown_operation():
    registry = PromptRegistry()
    assert registry.get("REALITY").operation == "REALITY_UPDATE"
    assert registry.get("RED_TEAM").capability == "T3"
    with pytest.raises(DomainError, match="not registered"):
        registry.get("NOT_AN_OPERATION")


def test_router_escalates_critical_without_fallback():
    route = ModelRouter().route("REALITY_UPDATE", "CRITICAL")
    assert route.tier == "T3"
    assert route.allow_lower_capability_fallback is False


def test_structured_success_records_complete_ledger():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    service = runtime(repo, [ProviderResult(valid_output(text="candidate"), 120, 20, 10)])
    result = service.execute(project, operation="REALITY_UPDATE", user_input="new information")
    run = result["run"]
    assert run["outcome"] == "SUCCEEDED"
    assert {
        "provider",
        "model",
        "prompt_id",
        "prompt_version",
        "methodology_version",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "retry_count",
        "estimated_cost_usd",
    } <= run.keys()
    assert run["input_tokens"] == 120
    assert repo.cost_entries[-1]["price_snapshot_id"] == "prices-v1"
    assert repo.get_resource(project, run["input_message_id"], "MESSAGE").status == "PERSISTED"


def test_invalid_json_gets_one_schema_aware_retry():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    provider = FakeProvider(["not json", valid_output(text="fixed")])
    service = AIExecutionService(repo, provider, registry=PromptRegistry())
    result = service.execute(project, operation="QUESTION_REFRAME", user_input="reframe")
    assert result["run"]["retry_count"] == 1
    assert len(provider.calls) == 2
    assert "Retry once" in provider.calls[1]["messages"][-1]["content"]


def test_schema_retry_exhaustion_is_safe_and_audited():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    service = runtime(repo, ['{"items":[]}', '{"status":"CONFIRMED","items":[]}'])
    with pytest.raises(DomainError) as caught:
        service.execute(project, operation="PERCEPTION_SYNTHESIS", user_input="synthesize")
    assert caught.value.code == "AI_SCHEMA_RETRY_EXHAUSTED"
    assert repo.ai_runs[-1]["outcome"] == "FAILED"
    assert repo.ai_runs[-1]["retry_count"] == 1
    assert "CONFIRMED" not in json.dumps(repo.ai_runs[-1])


class TinyRouter:
    def route(self, operation: str, consequentiality: str = "MEDIUM"):
        return Route(operation, "STANDARD_REASONING", "T2", "LOW", 1, 100, False)


def test_input_budget_rejection_does_not_call_provider():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    provider = FakeProvider([valid_output()])
    service = AIExecutionService(repo, provider, registry=PromptRegistry(), router=TinyRouter())
    with pytest.raises(DomainError) as caught:
        service.execute(project, operation="REALITY_UPDATE", user_input="too large")
    assert caught.value.code == "AI_INPUT_BUDGET_EXCEEDED"
    assert provider.calls == []


def test_t3_never_uses_t1_model():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    service = runtime(
        repo,
        [valid_output()],
        config=RuntimeConfig({"T1": "cheap"}, {}, "unpriced"),
    )
    with pytest.raises(DomainError) as caught:
        service.execute(project, operation="RED_TEAM", user_input="challenge")
    assert caught.value.code == "AI_MODEL_NOT_CONFIGURED"


def test_ai_cannot_confirm_human_owned_values():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    output = valid_output(confirmed_by_human=True, value="mandatory")
    service = runtime(repo, [output])
    with pytest.raises(DomainError) as caught:
        service.execute(project, operation="VALUE_BOUNDARY_SUGGESTION", user_input="suggest")
    assert caught.value.code == "AI_AUTHORITY_VIOLATION"
    assert repo.ai_runs[-1]["outcome"] == "FAILED"


def test_system_actor_cannot_directly_confirm_roadmap():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    project.stage = "OUTCOME"
    with pytest.raises(DomainError) as caught:
        CTFService(repo).create_resource(
            project, "ROADMAP", {"status": "CONFIRMED", "immutable": True}, None, "SYSTEM"
        )
    assert caught.value.code == "HUMAN_AUTHORITY_REQUIRED"


def test_provider_failure_is_safe_and_secret_is_not_persisted():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    secret = "sk-super-secret"
    service = runtime(repo, [RuntimeError(secret)])
    with pytest.raises(DomainError) as caught:
        service.execute(project, operation="REALITY_UPDATE", user_input="safe input")
    assert caught.value.code == "AI_PROVIDER_FAILURE"
    assert secret not in json.dumps(repo.ai_runs)
    assert secret not in json.dumps([event.public() for event in repo.audit_events])


def test_ai_run_api_is_tenant_isolated(client):
    first = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "one"}).json()
    second = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "two"}).json()
    project = client.post(
        "/api/v1/projects",
        headers={"X-Session-Token": first["token"]},
        json={"entry_family": "CREATION", "entry_type": "PROBLEM", "initial_input": "x"},
    ).json()
    response = client.get(
        f"/api/v1/projects/{project['id']}/ai/runs",
        headers={"X-Session-Token": second["token"]},
    )
    assert response.status_code == 403


def test_execute_api_and_run_inspection(client, project):
    previous = api_ai_execution.provider
    api_ai_execution.provider = FakeProvider([valid_output(text="proposal")])
    try:
        response = client.post(
            f"/api/v1/projects/{project['project']['id']}/ai/execute",
            headers=project["headers"],
            json={"operation": "REALITY_UPDATE", "user_input": "capture reality"},
        )
        assert response.status_code == 200
        run_id = response.json()["run"]["id"]
        runs = client.get(
            f"/api/v1/projects/{project['project']['id']}/ai/runs",
            headers=project["headers"],
        ).json()
        assert runs[-1]["id"] == run_id
    finally:
        api_ai_execution.provider = previous


def test_readiness_endpoint_is_authenticated_and_marks_fake_non_production(client, project):
    previous = api_ai_execution.provider
    api_ai_execution.provider = FakeProvider(fixture_mode=True)
    try:
        unauthorized = client.get("/api/v1/ai/readiness")
        assert unauthorized.status_code == 403
        response = client.get("/api/v1/ai/readiness", headers=project["headers"])
        assert response.status_code == 200
        assert response.json()["provider"] == "FAKE"
        assert response.json()["non_production"] is True
        assert "api_key" not in json.dumps(response.json()).lower()
    finally:
        api_ai_execution.provider = previous


def test_generator_ai_is_explicit_and_manual_api_remains(client, project):
    previous = generator_ai_execution.provider
    generator_ai_execution.provider = FakeProvider([valid_output(text="candidate reality")])
    try:
        ai_response = client.post(
            f"/api/v1/projects/{project['project']['id']}/reality/generate",
            headers=project["headers"],
            json={"data": {"prompt": "propose reality"}, "execute_ai": True},
        )
        assert ai_response.status_code == 201
        assert ai_response.json()["items"][0]["status"] == "PROPOSED"

        manual = client.post(
            f"/api/v1/projects/{project['project']['id']}/resources/note",
            headers=project["headers"],
            json={"data": {"text": "manual"}},
        )
        assert manual.status_code == 201
        assert manual.json()["provenance"] == "USER"
    finally:
        generator_ai_execution.provider = previous


def test_ollama_openai_protocol_retries_without_response_format_and_estimates_usage():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": valid_output(text="local candidate")}}
                ]
            },
        )

    provider = OllamaProvider(
        base_url="http://ollama:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.execute(
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": "local request"}],
        max_output_tokens=500,
    )
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in requests[1]
    assert result.input_tokens > 0
    assert result.output_tokens > 0


def test_ollama_readiness_reports_required_model_availability():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})

    provider = OllamaProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    status = provider.readiness(["qwen2.5:3b", "qwen2.5:7b"])
    assert status["reachable"] is True
    assert status["models"] == {"qwen2.5:3b": False, "qwen2.5:7b": True}
    assert "base_url" not in json.dumps(status).lower()


def test_ollama_missing_runtime_returns_safe_actionable_error_without_secret():
    secret = "do-not-leak"

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret)

    provider = OllamaProvider(
        base_url=f"http://{secret}@localhost:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DomainError) as caught:
        provider.execute(
            model="qwen2.5:7b",
            messages=[{"role": "user", "content": "test"}],
            max_output_tokens=100,
        )
    assert caught.value.code == "AI_PROVIDER_UNREACHABLE"
    assert "Start Ollama" in caught.value.message
    assert secret not in caught.value.message
    assert secret not in json.dumps(provider.readiness(["qwen2.5:7b"]))


def test_explicit_fake_mode_returns_schema_valid_operation_fixture(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "fake")
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    service = AIExecutionService.from_env(repo)
    result = service.execute(
        project,
        operation="QUESTION_REFRAME",
        user_input="exercise the complete UI",
    )
    assert result["run"]["provider"] == "FAKE"
    assert result["output"]["status"] == "PROPOSED"
    assert result["output"]["items"][0]["prompt_id"] == "QUESTION_PROMPT"
    assert service.readiness()["non_production"] is True


def test_ollama_blocks_t3_and_t4_by_default_without_provider_call():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    provider = FakeProvider([valid_output()])
    provider.name = "OLLAMA"
    service = AIExecutionService(
        repo,
        provider,
        registry=PromptRegistry(),
        config=RuntimeConfig(
            {"T1": "small", "T2": "standard", "T3": "critical", "T4": "verify"},
            {},
            "local",
        ),
    )
    with pytest.raises(DomainError) as caught:
        service.execute(project, operation="RED_TEAM", user_input="challenge")
    assert caught.value.code == "AI_LOCAL_TIER_NOT_ALLOWED"
    assert provider.calls == []


def test_ollama_t3_requires_explicit_flag_and_never_downgrades():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    provider = FakeProvider([valid_output()])
    provider.name = "OLLAMA"
    service = AIExecutionService(
        repo,
        provider,
        registry=PromptRegistry(),
        config=RuntimeConfig({"T1": "small", "T3": "critical"}, {}, "local", True, False),
    )
    result = service.execute(project, operation="RED_TEAM", user_input="challenge")
    assert provider.calls[0]["model"] == "critical"
    assert result["run"]["tier"] == "T3"


def test_provider_selection_never_falls_back_to_fake(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    service = AIExecutionService.from_env(InMemoryRepository())
    assert isinstance(service.provider, OllamaProvider)
    assert service.provider.name == "OLLAMA"

    monkeypatch.setenv("AI_PROVIDER", "unknown-provider")
    unconfigured = AIExecutionService.from_env(InMemoryRepository())
    assert unconfigured.provider is None
    assert unconfigured.readiness()["configured"] is False


def test_ollama_env_supports_per_tier_models_timeout_and_capability_flags(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL_MAP", '{"T1":"local-small","T2":"local-medium"}')
    monkeypatch.setenv("OLLAMA_MODEL_T2", "local-medium-override")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("AI_LOCAL_ALLOW_T3", "true")
    config = RuntimeConfig.from_env()
    provider = OllamaProvider.from_env()
    assert config.models["T1"] == "local-small"
    assert config.models["T2"] == "local-medium-override"
    assert config.local_allow_t3 is True
    assert config.local_allow_t4 is False
    assert provider.timeout_seconds == 45


def test_user_input_not_duplicated_in_provider_payload():
    repo = InMemoryRepository()
    project, _ = project_in(repo)
    unique = "UNIQUE_USER_PHRASE_NOT_DUPLICATED_XYZ"
    service = runtime(repo, [valid_output(text="draft")])
    service.execute(project, operation="QUESTION_REFRAME", user_input=unique)
    messages = service.provider.calls[0]["messages"]
    system = json.loads(messages[0]["content"])
    assert unique not in json.dumps(system.get("context", {}))
    assert "current_user_input" not in system.get("context", {})
    assert messages[1]["content"] == unique
    blob = json.dumps(messages)
    assert blob.count(unique) == 1

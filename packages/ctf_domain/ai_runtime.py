from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Protocol

import httpx
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .errors import DomainError, require
from .model_router import AICostLedger, ContextCompiler, ModelRouter, Route
from .models import Project, new_id, now_iso
from .repository import InMemoryRepository

ROOT = Path(__file__).resolve().parents[2]
INPUT_BUDGETS = {"SMALL": 4_000, "NORMAL": 16_000, "DEEP": 24_000}
CAPABILITIES = {"T0", "T1", "T2", "T3", "T4"}
LOCAL_DEFAULT_MODELS = {
    "T1": "qwen2.5:3b",
    "T2": "qwen2.5:7b",
    "T3": "qwen2.5:14b",
    "T4": "qwen2.5:14b",
}


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
OPERATION_ALIASES = {
    "REALITY": "REALITY_UPDATE",
    "QUESTION": "QUESTION_REFRAME",
    "PERCEPTION": "PERCEPTION_SYNTHESIS",
    "OPPORTUNITY": "OPPORTUNITY_GENERATION",
    "SPARK": "SPARK_GENERATION",
    "IDEA": "IDEA_BLUEPRINT",
    "ROADMAP": "ROADMAP_REPLAN",
    "NBA": "NEXT_BEST_ACTION",
    "VALUE_ASSESSMENT": "REALIZED_VALUE",
    "TRANSFORMATION_ASSESSMENT": "TRANSFORMATION",
}


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    id: str
    version: str
    operation: str
    stage: str
    capability: str
    effort: str
    input_budget: str
    output_tokens: int
    output_schema_name: str
    output_schema: dict[str, Any]
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    instructions: str
    policy: str
    methodology_version: str


class PromptRegistry:
    """Validated, immutable view of the YAML prompt registry."""

    REQUIRED: ClassVar[set[str]] = {
        "id",
        "version",
        "operation",
        "stage",
        "capability",
        "effort",
        "input_budget",
        "output_tokens",
        "output_schema",
        "allowed",
        "forbidden",
    }

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self.path = Path(registry_path or ROOT / "prompts" / "registry.yaml").resolve()
        self._by_operation: dict[str, list[PromptDefinition]] = {}
        self.constitution = ""
        self.registry_version = ""
        self.methodology_version = ""
        self._load()

    def _yaml(self, path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise DomainError("PROMPT_REGISTRY_INVALID", f"Cannot load prompt metadata: {exc}.", 500) from exc
        require(isinstance(data, dict), "PROMPT_REGISTRY_INVALID", "Prompt YAML must be an object.", 500)
        return data

    def _resolve(self, value: str) -> Path:
        candidate = Path(value)
        return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()

    def _load(self) -> None:
        registry = self._yaml(self.path)
        self.registry_version = str(registry.get("registry_version", ""))
        self.methodology_version = str(registry.get("methodology_version", ""))
        require(self.registry_version and self.methodology_version, "PROMPT_REGISTRY_INVALID", "Registry versions are required.", 500)
        rules = registry.get("rules", {})
        require(
            rules.get("structured_output_required") is True
            and rules.get("max_schema_retries") == 1
            and rules.get("human_gate_decision_allowed") is False
            and rules.get("persist_hidden_chain_of_thought") is False,
            "PROMPT_REGISTRY_INVALID",
            "Registry safety policy is missing or weakened.",
            500,
        )
        constitution_path = self._resolve(str(registry.get("constitution", "")))
        schemas = self._yaml(self._resolve(str(registry.get("schemas", ""))))
        try:
            self.constitution = constitution_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DomainError("PROMPT_REGISTRY_INVALID", "Prompt constitution is missing.", 500) from exc
        seen_ids: set[tuple[str, str]] = set()
        for slice_ref in registry.get("slices", {}).values():
            slice_data = self._yaml(self._resolve(str(slice_ref.get("file", ""))))
            defaults = dict(slice_data.get("defaults", {}))
            policy = str(slice_data.get("policy", ""))
            require(bool(policy), "PROMPT_REGISTRY_INVALID", "Slice operation policy is required.", 500)
            for raw in slice_data.get("prompts", []):
                merged = {**defaults, **dict(raw)}
                missing = self.REQUIRED - merged.keys()
                require(not missing, "PROMPT_REGISTRY_INVALID", f"Prompt metadata missing: {sorted(missing)}.", 500)
                capability = str(merged["capability"]).upper()
                input_budget = str(merged["input_budget"]).upper()
                schema_name = str(merged["output_schema"])
                require(capability in CAPABILITIES, "PROMPT_REGISTRY_INVALID", "Unknown capability tier.", 500)
                require(input_budget in INPUT_BUDGETS, "PROMPT_REGISTRY_INVALID", "Unknown input budget.", 500)
                require(schema_name in schemas, "PROMPT_REGISTRY_INVALID", f"Schema {schema_name} is unresolved.", 500)
                try:
                    Draft202012Validator.check_schema(schemas[schema_name])
                except SchemaError as exc:
                    raise DomainError("PROMPT_REGISTRY_INVALID", f"Schema {schema_name} is invalid.", 500) from exc
                identity = (str(merged["id"]), str(merged["version"]))
                require(
                    all(
                        (
                            identity[0],
                            identity[1],
                            str(merged["operation"]),
                            str(merged["stage"]),
                        )
                    )
                    and isinstance(merged["allowed"], list)
                    and isinstance(merged["forbidden"], list),
                    "PROMPT_REGISTRY_INVALID",
                    "Prompt identity, policy lists and version are required.",
                    500,
                )
                require(identity not in seen_ids, "PROMPT_REGISTRY_INVALID", "Prompt id/version must be unique.", 500)
                seen_ids.add(identity)
                prompt = PromptDefinition(
                    id=identity[0],
                    version=identity[1],
                    operation=str(merged["operation"]).upper(),
                    stage=str(merged["stage"]).upper(),
                    capability=capability,
                    effort=str(merged["effort"]).upper(),
                    input_budget=input_budget,
                    output_tokens=int(merged["output_tokens"]),
                    output_schema_name=schema_name,
                    output_schema=deepcopy(schemas[schema_name]),
                    allowed=tuple(str(item) for item in merged["allowed"]),
                    forbidden=tuple(str(item) for item in merged["forbidden"]),
                    instructions=str(merged.get("instructions", "")),
                    policy=policy,
                    methodology_version=self.methodology_version,
                )
                require(prompt.output_tokens > 0, "PROMPT_REGISTRY_INVALID", "Output budget must be positive.", 500)
                self._by_operation.setdefault(prompt.operation, []).append(prompt)

    def get(self, operation: str, version: str | None = None) -> PromptDefinition:
        canonical = OPERATION_ALIASES.get(operation.upper(), operation.upper())
        choices = self._by_operation.get(canonical, [])
        require(bool(choices), "AI_OPERATION_NOT_ALLOWED", f"AI operation {canonical} is not registered.", 404)
        if version is not None:
            choices = [item for item in choices if item.version == version]
            require(bool(choices), "PROMPT_VERSION_NOT_FOUND", "Prompt version is not registered.", 404)
        return choices[-1]

    def operations(self) -> list[str]:
        return sorted(self._by_operation)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    content: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


class ModelProvider(Protocol):
    name: str

    def execute(
        self, *, model: str, messages: list[dict[str, str]], max_output_tokens: int, temperature: float = 0
    ) -> ProviderResult: ...

    def readiness(self, required_models: list[str]) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    name = "OPENAI_COMPATIBLE"

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float = 30.0) -> None:
        require(bool(base_url and api_key), "AI_PROVIDER_NOT_CONFIGURED", "AI provider credentials are not configured.", 503)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> OpenAICompatibleProvider:
        return cls(
            base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("AI_API_KEY", ""),
            timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "30")),
        )

    def execute(
        self, *, model: str, messages: list[dict[str, str]], max_output_tokens: int, temperature: float = 0
    ) -> ProviderResult:
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_output_tokens,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage", {})
            content = payload["choices"][0]["message"]["content"]
            return ProviderResult(
                content=content,
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                cached_input_tokens=int(usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise DomainError("AI_PROVIDER_FAILURE", "The AI provider request failed safely.", 503) from exc

    def readiness(self, required_models: list[str]) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            available = {
                str(item.get("id"))
                for item in response.json().get("data", [])
                if isinstance(item, dict) and item.get("id")
            }
            return {
                "configured": True,
                "reachable": True,
                "required_models": required_models,
                "models": {model: model in available for model in required_models},
                "limitations": [],
            }
        except (httpx.HTTPError, TypeError, ValueError):
            return {
                "configured": True,
                "reachable": False,
                "required_models": required_models,
                "models": {model: False for model in required_models},
                "limitations": ["Provider reachability or model availability could not be verified."],
                "error": {
                    "code": "AI_PROVIDER_UNREACHABLE",
                    "message": "The configured AI provider is unreachable. Check its service and network configuration.",
                },
            }


class OllamaProvider:
    """Ollama adapter using its OpenAI-compatible chat contract and native discovery API."""

    name = "OLLAMA"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        require(bool(base_url), "AI_PROVIDER_NOT_CONFIGURED", "Ollama base URL is not configured.", 503)
        normalized = base_url.rstrip("/")
        self.api_root = normalized.removesuffix("/v1")
        self.base_url = f"{self.api_root}/v1"
        self.timeout_seconds = timeout_seconds
        self._client = client

    @classmethod
    def from_env(cls) -> OllamaProvider:
        return cls(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            timeout_seconds=float(
                os.getenv("OLLAMA_TIMEOUT_SECONDS", os.getenv("AI_TIMEOUT_SECONDS", "120"))
            ),
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        request = self._client.request if self._client else httpx.request
        return request(method, url, timeout=self.timeout_seconds, **kwargs)

    @staticmethod
    def _estimated_tokens(value: str) -> int:
        return max(1, (len(value) + 3) // 4)

    def execute(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float = 0,
    ) -> ProviderResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            response = self._request("POST", f"{self.base_url}/chat/completions", json=payload)
            if response.status_code in {400, 404, 422}:
                # Older Ollama versions/models may reject response_format while still supporting /v1.
                payload.pop("response_format")
                response = self._request("POST", f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            require(isinstance(content, str), "AI_PROVIDER_FAILURE", "Ollama returned an invalid response.", 503)
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            input_tokens = int(usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or 0)
            if not input_tokens:
                input_tokens = self._estimated_tokens(
                    "".join(str(message.get("content", "")) for message in messages)
                )
            if not output_tokens:
                output_tokens = self._estimated_tokens(content)
            return ProviderResult(content, input_tokens, output_tokens)
        except DomainError:
            raise
        except httpx.RequestError as exc:
            raise DomainError(
                "AI_PROVIDER_UNREACHABLE",
                "Ollama is unreachable. Start Ollama and verify OLLAMA_BASE_URL, then check AI readiness.",
                503,
            ) from exc
        except (httpx.HTTPStatusError, KeyError, TypeError, ValueError) as exc:
            raise DomainError(
                "AI_PROVIDER_FAILURE",
                "Ollama rejected or returned an invalid request. Check readiness and the configured model.",
                503,
            ) from exc

    def readiness(self, required_models: list[str]) -> dict[str, Any]:
        try:
            response = self._request("GET", f"{self.api_root}/api/tags")
            response.raise_for_status()
            body = response.json()
            available = {
                str(item.get("name") or item.get("model"))
                for item in body.get("models", [])
                if isinstance(item, dict) and (item.get("name") or item.get("model"))
            }
            return {
                "configured": True,
                "reachable": True,
                "required_models": required_models,
                "models": {model: model in available for model in required_models},
                "limitations": [
                    "Token usage may be estimated when Ollama omits usage metadata.",
                    "Structured JSON is validated by CTF; older Ollama versions may ignore response_format.",
                ],
            }
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return {
                "configured": True,
                "reachable": False,
                "required_models": required_models,
                "models": {model: False for model in required_models},
                "limitations": [
                    "Local T3/T4 are disabled by default.",
                    "Model availability could not be checked while Ollama is unreachable.",
                ],
                "error": {
                    "code": "AI_PROVIDER_UNREACHABLE",
                    "message": "Ollama is unreachable. Start it, verify OLLAMA_BASE_URL, and pull required models.",
                },
            }


class FakeProvider:
    name = "FAKE"

    def __init__(
        self,
        responses: list[str | ProviderResult | Exception] | None = None,
        *,
        fixture_mode: bool = False,
    ) -> None:
        self.responses = list(responses or [])
        self.fixture_mode = fixture_mode
        self.calls: list[dict[str, Any]] = []

    def execute(
        self, *, model: str, messages: list[dict[str, str]], max_output_tokens: int, temperature: float = 0
    ) -> ProviderResult:
        self.calls.append({"model": model, "messages": deepcopy(messages), "max_output_tokens": max_output_tokens})
        if not self.responses and self.fixture_mode:
            prompt_id = "UNKNOWN"
            try:
                system = json.loads(messages[0]["content"])
                prompt_id = str(system.get("prompt", {}).get("id", "UNKNOWN"))
            except (IndexError, KeyError, TypeError, ValueError):
                pass
            fixture = json.dumps(
                {
                    "status": "PROPOSED",
                    "items": [
                        {
                            "fixture": True,
                            "prompt_id": prompt_id,
                            "text": f"Deterministic local fixture for {prompt_id}",
                        }
                    ],
                    "summary": "Non-production deterministic fixture.",
                }
            )
            return ProviderResult(
                fixture,
                max(1, sum(len(message["content"]) for message in messages) // 4),
                max(1, len(fixture) // 4),
            )
        require(bool(self.responses), "AI_PROVIDER_FAILURE", "Fake provider has no queued response.", 503)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, ProviderResult):
            return response
        return ProviderResult(response, max(1, sum(len(m["content"]) for m in messages) // 4), max(1, len(response) // 4))

    def readiness(self, required_models: list[str]) -> dict[str, Any]:
        return {
            "configured": True,
            "reachable": True,
            "required_models": required_models,
            "models": {model: True for model in required_models},
            "limitations": [
                "Non-production deterministic fixtures only; no model reasoning is performed."
            ],
            "non_production": True,
        }


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    models: dict[str, str]
    pricing: dict[str, dict[str, str]]
    price_snapshot_id: str
    local_allow_t3: bool = False
    local_allow_t4: bool = False

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        default_models = {"T1": "efficient", "T2": "standard", "T3": "critical", "T4": "verification"}
        selected = os.getenv("AI_PROVIDER", "").strip().lower()
        if selected == "ollama":
            default_models = LOCAL_DEFAULT_MODELS
        try:
            provider_map = os.getenv("OLLAMA_MODEL_MAP", "{}") if selected == "ollama" else "{}"
            models = {
                **default_models,
                **json.loads(os.getenv("AI_MODEL_MAP", "{}")),
                **json.loads(provider_map),
            }
            pricing = json.loads(os.getenv("AI_PRICING_MAP", "{}"))
        except (json.JSONDecodeError, TypeError) as exc:
            raise DomainError("AI_CONFIG_INVALID", "AI model or pricing configuration is invalid.", 500) from exc
        if selected == "ollama":
            for tier in ("T1", "T2", "T3", "T4"):
                models[tier] = os.getenv(f"OLLAMA_MODEL_{tier}", models[tier])
        return cls(
            models,
            pricing,
            os.getenv("AI_PRICE_SNAPSHOT_ID", "unpriced"),
            _env_flag("AI_LOCAL_ALLOW_T3"),
            _env_flag("AI_LOCAL_ALLOW_T4"),
        )


class AIExecutionService:
    def __init__(
        self,
        repo: InMemoryRepository,
        provider: ModelProvider | None = None,
        *,
        registry: PromptRegistry | None = None,
        router: ModelRouter | None = None,
        config: RuntimeConfig | None = None,
    ) -> None:
        self.repo = repo
        self.provider = provider
        self.registry = registry or PromptRegistry()
        self.router = router or ModelRouter()
        self.config = config or RuntimeConfig.from_env()
        self.compiler = ContextCompiler()
        self.ledger = AICostLedger(repo)

    @classmethod
    def from_env(cls, repo: InMemoryRepository) -> AIExecutionService:
        selected = os.getenv("AI_PROVIDER", "").strip().lower()
        provider: ModelProvider | None = None
        if selected in {"openai", "openai-compatible"} and os.getenv("AI_API_KEY"):
            provider = OpenAICompatibleProvider.from_env()
        elif selected == "ollama":
            provider = OllamaProvider.from_env()
        elif selected == "fake":
            provider = FakeProvider(fixture_mode=True)
        return cls(repo, provider)

    def readiness(self) -> dict[str, Any]:
        selected = os.getenv("AI_PROVIDER", "").strip().lower()
        selected_name = {
            "openai": "OPENAI_COMPATIBLE",
            "openai-compatible": "OPENAI_COMPATIBLE",
            "ollama": "OLLAMA",
            "fake": "FAKE",
        }.get(selected, selected.upper() or "NONE")
        provider_type = self.provider.name if self.provider else selected_name
        allowed_tiers = ["T1", "T2"]
        if provider_type != "OLLAMA" or self.config.local_allow_t3:
            allowed_tiers.append("T3")
        if provider_type != "OLLAMA" or self.config.local_allow_t4:
            allowed_tiers.append("T4")
        required_models = list(
            dict.fromkeys(
                self.config.models[tier]
                for tier in allowed_tiers
                if self.config.models.get(tier)
            )
        )
        if not self.provider:
            return {
                "provider": provider_type,
                "configured": False,
                "reachable": False,
                "ready": False,
                "required_models": required_models,
                "models": {model: False for model in required_models},
                "allowed_tiers": [],
                "limitations": ["No AI provider is configured; manual workflows remain available."],
            }
        status = self.provider.readiness(required_models)
        limitations = list(status.get("limitations", []))
        if provider_type == "OLLAMA":
            disabled = [tier for tier in ("T3", "T4") if tier not in allowed_tiers]
            if disabled:
                limitations.append(
                    f"Local {'/'.join(disabled)} execution is disabled until explicitly enabled and validated."
                )
        status["limitations"] = limitations
        return {
            "provider": provider_type,
            **status,
            "ready": bool(status.get("reachable"))
            and all(status.get("models", {}).values()),
            "allowed_tiers": allowed_tiers,
        }

    @staticmethod
    def _tokens(value: Any) -> int:
        return max(1, (len(json.dumps(value, separators=(",", ":"), ensure_ascii=False)) + 3) // 4)

    def _route(self, prompt: PromptDefinition, consequentiality: str) -> Route:
        try:
            route = self.router.route(prompt.operation, consequentiality)
        except DomainError as exc:
            if exc.code != "MODEL_ROUTE_NOT_FOUND":
                raise
            route = Route(
                prompt.operation,
                {"T1": "EFFICIENT_AI", "T2": "STANDARD_REASONING", "T3": "CRITICAL_REASONING", "T4": "INDEPENDENT_VERIFICATION"}[prompt.capability],
                prompt.capability,
                prompt.effort,
                INPUT_BUDGETS[prompt.input_budget],
                prompt.output_tokens,
                False,
            )
            if consequentiality.upper() == "CRITICAL" and route.tier in {"T1", "T2"}:
                route = Route(route.operation, "CRITICAL_REASONING", "T3", "HIGH", max(route.max_input_tokens, 16_000), max(route.max_output_tokens, 1_500), False)
        return route

    def _safe_authority_check(self, output: dict[str, Any]) -> None:
        require(output.get("status") in {"PROPOSED", "CANDIDATE"}, "AI_AUTHORITY_VIOLATION", "AI output must remain proposed.", 422)

        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    lowered = child_key.lower()
                    if lowered in {"gate_decision", "confirmed_by_human", "human_decision"}:
                        raise DomainError("AI_AUTHORITY_VIOLATION", "AI output attempted a Human-owned action.", 422)
                    if lowered in {"confirmed", "immutable"} and child is True:
                        raise DomainError("AI_AUTHORITY_VIOLATION", "AI output attempted to confirm a value.", 422)
                    if lowered == "status" and str(child).upper() in {"CONFIRMED", "SELECTED", "ACTIVE", "COMPLETED"}:
                        raise DomainError("AI_AUTHORITY_VIOLATION", "AI output attempted to confirm a record.", 422)
                    visit(child, lowered)
            elif isinstance(value, list):
                for child in value:
                    visit(child, key)

        visit(output)

    def _pricing(self, model: str) -> dict[str, Decimal]:
        raw = self.config.pricing.get(model, {})
        return {
            "input": Decimal(str(raw.get("input_per_mtok", "0"))),
            "cached": Decimal(str(raw.get("cached_input_per_mtok", "0"))),
            "output": Decimal(str(raw.get("output_per_mtok", "0"))),
        }

    def execute(
        self,
        project: Project,
        *,
        operation: str,
        user_input: str,
        consequentiality: str = "MEDIUM",
        prompt_version: str | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = self.registry.get(operation, prompt_version)
        route = self._route(prompt, consequentiality)
        require(bool(self.provider), "AI_PROVIDER_NOT_CONFIGURED", "No AI provider is configured.", 503)
        if self.provider.name == "OLLAMA":
            allowed = route.tier in {"T1", "T2"}
            allowed = allowed or (route.tier == "T3" and self.config.local_allow_t3)
            allowed = allowed or (route.tier == "T4" and self.config.local_allow_t4)
            require(
                allowed,
                "AI_LOCAL_TIER_NOT_ALLOWED",
                f"Local {route.tier} execution is disabled. Enable its explicit AI_LOCAL_ALLOW flag only after validating the configured model.",
                403,
            )
        model = self.config.models.get(route.tier)
        require(bool(model), "AI_MODEL_NOT_CONFIGURED", f"No model is configured for {route.tier}.", 503)
        evidence = [item.public() for item in self.repo.list_resources(project, "EVIDENCE")][-50:]
        memory = deepcopy(project.memory)
        if extra_context:
            memory["request_context"] = deepcopy(extra_context)
        context = self.compiler.compile(
            constitution=self.registry.constitution,
            policy=prompt.policy,
            authority_rules="AI creates PROPOSED/CANDIDATE output only. Never decide gates or confirm Human-owned records.",
            memory=memory,
            evidence=evidence,
            user_input=user_input,
            schema=prompt.output_schema,
        )
        input_tokens = (
            self._tokens(context)
            + self._tokens(
                {
                    "id": prompt.id,
                    "version": prompt.version,
                    "instructions": prompt.instructions,
                    "allowed": prompt.allowed,
                    "forbidden": prompt.forbidden,
                }
            )
            + self._tokens(user_input)
        )
        require(input_tokens <= route.max_input_tokens, "AI_INPUT_BUDGET_EXCEEDED", "Compiled AI context exceeds the routed input budget.", 413)
        pricing = self._pricing(model)
        reserved_tokens = input_tokens + min(route.max_output_tokens, prompt.output_tokens)
        reserved_cost = (
            Decimal(input_tokens) * pricing["input"]
            + Decimal(min(route.max_output_tokens, prompt.output_tokens)) * pricing["output"]
        ) / Decimal(1_000_000)
        self.repo.reserve_ai_quota(
            project.tenant_id,
            datetime.now(UTC).date().isoformat(),
            reserved_tokens,
            str(reserved_cost),
            int(os.getenv("CTF_AI_DAILY_TOKEN_QUOTA", "1000000")),
            os.getenv("CTF_AI_DAILY_COST_QUOTA_USD", "100"),
        )

        with self.repo.transaction():
            message = self.repo.create_resource(
                project,
                "MESSAGE",
                {"text": user_input, "information_type": "AI_EXECUTION_INPUT", "source": "USER"},
                status="PERSISTED",
                provenance="USER",
                immutable=True,
            )
            run = {
                "id": new_id("airun"),
                "project_id": project.id,
                "input_message_id": message.id,
                "operation": prompt.operation,
                "provider": self.provider.name,
                "model": model,
                "prompt_id": prompt.id,
                "prompt_version": prompt.version,
                "methodology_version": prompt.methodology_version,
                "capability": route.capability,
                "tier": route.tier,
                "reasoning_effort": route.reasoning_effort,
                "outcome": "STARTED",
                "input_tokens": input_tokens,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "estimated_cost_usd": "0.000000",
                "price_snapshot_id": self.config.price_snapshot_id,
                "retry_count": 0,
                "error": None,
                "created_at": now_iso(),
                "completed_at": None,
            }
            self.repo.ai_runs.append(run)
            self.repo.audit(project.id, "ai_run_started", "SYSTEM", {"run_id": run["id"], "operation": prompt.operation})
            self.repo.persist()

        system_message = {
            "role": "system",
            "content": json.dumps(
                {
                    "context": context,
                    "prompt": {
                        "id": prompt.id,
                        "version": prompt.version,
                        "instructions": prompt.instructions,
                        "allowed": prompt.allowed,
                        "forbidden": prompt.forbidden,
                    },
                    "response_contract": "Return only one compact JSON object matching output_schema. Prefer short fields. Do not include hidden reasoning or prose outside JSON.",
                },
                separators=(",", ":"),
            ),
        }
        messages = [system_message, {"role": "user", "content": user_input}]
        started = time.perf_counter()
        usage = {"input": 0, "cached": 0, "output": 0}
        output: dict[str, Any] | None = None
        safe_error: DomainError | None = None
        allowed_output = min(route.max_output_tokens, prompt.output_tokens)
        # Local tokenizers and character estimates disagree; allow modest headroom after the hard request cap.
        output_headroom = max(allowed_output, int(allowed_output * 1.25))
        for attempt in range(2):
            try:
                result = self.provider.execute(
                    model=model,
                    messages=messages,
                    max_output_tokens=allowed_output,
                )
                usage["input"] += result.input_tokens
                usage["cached"] += result.cached_input_tokens
                usage["output"] += result.output_tokens
                require(
                    result.input_tokens <= route.max_input_tokens,
                    "AI_INPUT_BUDGET_EXCEEDED",
                    "Provider-reported AI input exceeds the routed input budget.",
                    422,
                )
                # Prefer measured content size. Provider-reported completion tokens can be inflated
                # (especially on Ollama) and should not reject an otherwise schema-valid draft.
                content_tokens = self._tokens(result.content)
                require(
                    content_tokens <= output_headroom,
                    "AI_OUTPUT_BUDGET_EXCEEDED",
                    "AI output exceeds the routed output budget.",
                    422,
                )
                parsed = json.loads(result.content)
                require(isinstance(parsed, dict), "AI_OUTPUT_INVALID", "AI output must be a JSON object.", 422)
                Draft202012Validator(prompt.output_schema).validate(parsed)
                self._safe_authority_check(parsed)
                output = parsed
                break
            except (json.JSONDecodeError, ValidationError, DomainError) as exc:
                if isinstance(exc, DomainError) and exc.code != "AI_OUTPUT_INVALID":
                    safe_error = exc
                    break
                if attempt == 1:
                    safe_error = DomainError("AI_SCHEMA_RETRY_EXHAUSTED", "AI output did not satisfy the registered schema.", 422)
                    break
                run["retry_count"] = 1
                messages.append({"role": "assistant", "content": "The prior response was invalid."})
                messages.append(
                    {
                        "role": "user",
                        "content": "Retry once. Return only JSON matching the registered schema with status PROPOSED or CANDIDATE.",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary must fail closed
                safe_error = exc if isinstance(exc, DomainError) else DomainError("AI_PROVIDER_FAILURE", "The AI provider request failed safely.", 503)
                break

        latency_ms = int((time.perf_counter() - started) * 1000)
        with self.repo.transaction():
            ledger = self.ledger.record(
                project_id=project.id,
                operation=prompt.operation,
                provider=self.provider.name,
                model=model,
                capability=route.capability,
                reasoning_effort=route.reasoning_effort,
                input_tokens=usage["input"],
                cached_input_tokens=usage["cached"],
                output_tokens=usage["output"],
                input_per_mtok=pricing["input"],
                cached_input_per_mtok=pricing["cached"],
                output_per_mtok=pricing["output"],
                price_snapshot_id=self.config.price_snapshot_id,
                latency_ms=latency_ms,
            )
            run.update(
                {
                    "outcome": "SUCCEEDED" if output is not None else "FAILED",
                    "input_tokens": usage["input"] or input_tokens,
                    "cached_input_tokens": usage["cached"],
                    "output_tokens": usage["output"],
                    "latency_ms": latency_ms,
                    "estimated_cost_usd": ledger["estimated_cost_usd"],
                    "error": None if output is not None else {"code": safe_error.code if safe_error else "AI_PROVIDER_FAILURE", "message": safe_error.message if safe_error else "The AI provider request failed safely."},
                    "completed_at": now_iso(),
                }
            )
            self.repo.audit(project.id, "ai_run_completed", "SYSTEM", {"run_id": run["id"], "outcome": run["outcome"], "retry_count": run["retry_count"]})
            self.repo.persist()
        if safe_error:
            raise safe_error
        return {"run": deepcopy(run), "output": output}

    def runs(self, project: Project) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self.repo.ai_runs if item["project_id"] == project.id]

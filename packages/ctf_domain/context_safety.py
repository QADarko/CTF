"""Safe AI request context and raw-telemetry exclusion (CTF-011)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .errors import DomainError

ALLOWED_REQUEST_CONTEXT_KEYS = ("focus", "selected_ids", "resource_refs", "constraints")

FORBIDDEN_RESOURCE_KINDS = frozenset(
    {
        "REALITY_EVENT",
        "EXECUTION_EVENT",
        "ATTACHMENT",
        "ERI_CONNECTION",
        "METRIC_BINDING",
    }
)
DEFAULT_EXCLUDED_RESOURCE_KINDS = frozenset(
    {
        *FORBIDDEN_RESOURCE_KINDS,
        "DOCUMENT_CHUNK",
    }
)

UNSAFE_CONTEXT_KEYS = frozenset(
    {
        "raw_payload",
        "raw_measurement",
        "raw_telemetry",
        "khal_raw",
        "khal_payload",
        "upstream_payload",
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "credential",
        "credentials",
        "authorization",
        "bearer",
        "credential_reference",
        "eri_connection",
        "provider_credentials",
        "connection_config",
    }
)


class AIRequestContext(BaseModel):
    focus: str | None = None
    selected_ids: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def sanitize_request_context(
    raw: dict[str, Any] | None,
    allowed_keys: tuple[str, ...],
) -> dict[str, Any]:
    payload = dict(raw or {})
    unknown = [key for key in payload if key not in allowed_keys]
    if unknown:
        raise DomainError(
            "AI_CONTEXT_FIELD_NOT_ALLOWED",
            f"Request context field(s) not allowed: {', '.join(sorted(unknown))}.",
            400,
        )
    unsafe = [key for key in payload if key.lower() in UNSAFE_CONTEXT_KEYS]
    if unsafe:
        raise DomainError(
            "AI_CONTEXT_FIELD_NOT_ALLOWED",
            "Request context must not carry credentials or raw telemetry.",
            400,
        )
    return {key: payload[key] for key in allowed_keys if key in payload}


def is_unsafe_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in UNSAFE_CONTEXT_KEYS:
        return True
    return any(token in lowered for token in ("api_key", "raw_payload", "raw_measurement", "credential"))


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_value(child) for key, child in value.items() if not is_unsafe_key(str(key))}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def assert_no_forbidden_kind(kind: str) -> None:
    if kind.upper() in FORBIDDEN_RESOURCE_KINDS:
        raise DomainError(
            "AI_CONTEXT_FIELD_NOT_ALLOWED",
            f"{kind} cannot enter compiled AI context.",
            400,
        )

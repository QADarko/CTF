from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SessionCreate(BaseModel):
    tenant_id: str = "public"


class ProjectCreate(BaseModel):
    entry_family: Literal["CREATION", "FUNDING", "DOCUMENT"]
    entry_type: str
    initial_input: str = Field(min_length=1, max_length=20_000)
    source: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entry_family", mode="before")
    @classmethod
    def normalize_entry_family(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        aliases = {"CREATE": "CREATION"}
        key = value.strip().upper()
        return aliases.get(key, key)


class UserInput(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    information_type: str = "USER_INPUT"
    provenance: Literal["USER"] = "USER"
    expected_version: int | None = None


class MemoryPatch(BaseModel):
    operations: list[dict[str, Any]]
    expected_version: int | None = None
    actor_type: Literal["HUMAN", "SYSTEM", "AI"] = "HUMAN"


class ResourceCreate(BaseModel):
    data: dict[str, Any]
    expected_version: int | None = None
    provenance: str = "USER"
    execute_ai: bool = False
    ai_operation: str | None = None
    consequentiality: str = "MEDIUM"
    prompt_version: str | None = None


class ResourcePatch(BaseModel):
    data: dict[str, Any]
    expected_version: int | None = None


class ResourceConfirm(BaseModel):
    expected_version: int | None = None
    actor_type: Literal["HUMAN"] = "HUMAN"


class GateDecision(BaseModel):
    decision: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = None
    actor_type: Literal["HUMAN", "AI", "SYSTEM"] = "HUMAN"


class RevisionTransition(BaseModel):
    target_stage: str
    expected_version: int | None = None


class ActionStatus(BaseModel):
    status: str
    expected_version: int | None = None


class RouteRequest(BaseModel):
    operation: str
    consequentiality: str = "MEDIUM"


class AIExecuteRequest(BaseModel):
    operation: str
    user_input: str = Field(min_length=1, max_length=50_000)
    consequentiality: str = "MEDIUM"
    prompt_version: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    persist_as: str | None = None
    expected_version: int | None = None


class UsageCreate(BaseModel):
    project_id: str
    operation: str
    provider: str
    model: str
    capability: str
    reasoning_effort: str
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    input_per_mtok: str
    cached_input_per_mtok: str
    output_per_mtok: str
    price_snapshot_id: str
    latency_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_usage(self) -> UsageCreate:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        try:
            prices = (
                Decimal(self.input_per_mtok),
                Decimal(self.cached_input_per_mtok),
                Decimal(self.output_per_mtok),
            )
        except InvalidOperation as exc:
            raise ValueError("AI prices must be decimals") from exc
        if any(price < 0 or not price.is_finite() for price in prices):
            raise ValueError("AI prices must be finite and non-negative")
        return self


class KHALConnect(BaseModel):
    base_url: str
    credential_reference: str


class ERIEventCreate(BaseModel):
    project_id: str
    provider: str
    external_event_id: str
    event_type: str
    subject: dict[str, Any] = Field(default_factory=dict)
    metric: str | None = None
    baseline: dict[str, Any] | None = None
    observed: dict[str, Any] | None = None
    observed_at: str
    generated_at: str | None = None
    source_confidence: float | None = None
    data_quality: str = "UNKNOWN"
    transformation_history: list[dict[str, Any]] = Field(default_factory=list)


class MetricBindingCreate(BaseModel):
    project_id: str
    ctf_metric_id: str
    provider: str = "KHAL"
    external_metric: str
    aggregation: str = "NONE"
    human_confirmed: bool = False

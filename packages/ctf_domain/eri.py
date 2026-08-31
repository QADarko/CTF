from __future__ import annotations

import json
import os
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from .errors import DomainError, require
from .models import Project, new_id, now_iso
from .repository import InMemoryRepository

EVENT_TYPES = {
    "STATE_CHANGE",
    "THRESHOLD_BREACH",
    "PERFORMANCE_DEVIATION",
    "ANOMALY",
    "FAILURE",
    "RECOVERY",
    "TREND_CHANGE",
    "RESOURCE_CHANGE",
    "ENVIRONMENT_CHANGE",
    "RISK_SIGNAL",
    "OPPORTUNITY_SIGNAL",
    "VALUE_MEASUREMENT",
    "TARGET_REACHED",
    "TARGET_MISSED",
    "OTHER",
}

DATA_QUALITY = {"VALID", "ESTIMATED", "MISSING", "STALE", "OUTLIER", "INVALID", "UNKNOWN"}


class ExternalRealityProvider(Protocol):
    name: str
    read_only: bool

    def assets(self, tenant_id: str) -> dict[str, Any]: ...
    def metrics(self, tenant_id: str) -> dict[str, Any]: ...
    def measurements(self, tenant_id: str, query: dict[str, Any]) -> dict[str, Any]: ...
    def readiness(self, tenant_id: str | None = None) -> dict[str, Any]: ...


class SecretResolver(Protocol):
    def resolve(self, reference: str) -> str: ...


class EnvironmentSecretResolver:
    """Resolve explicit env:// references without retaining secret values."""

    def resolve(self, reference: str) -> str:
        require(
            reference.startswith("env://"),
            "KHAL_SECRET_REFERENCE_INVALID",
            "KHAL credentials must use a supported secret reference.",
            503,
        )
        variable = reference.removeprefix("env://")
        require(
            bool(variable) and variable.replace("_", "").isalnum(),
            "KHAL_SECRET_REFERENCE_INVALID",
            "KHAL credentials must use a supported secret reference.",
            503,
        )
        value = os.getenv(variable, "")
        require(
            bool(value),
            "KHAL_CREDENTIAL_UNAVAILABLE",
            "KHAL credential is unavailable.",
            503,
        )
        return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class KHALProvider:
    """Read-only HTTP adapter for normalized KHAL external reality data."""

    name = "KHAL"
    read_only = True
    _SECRET_KEYS = frozenset(
        {"api_key", "apikey", "authorization", "credential", "password", "secret", "token"}
    )

    def __init__(
        self,
        *,
        base_url: str,
        credential_reference: str,
        tenant_mapping: dict[str, str],
        timeout_seconds: float = 10,
        page_size: int = 100,
        max_pages: int = 100,
        stale_after_seconds: float = 300,
        secret_resolver: SecretResolver | None = None,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        parsed_url = urlsplit(base_url)
        require(
            parsed_url.scheme in {"http", "https"}
            and bool(parsed_url.hostname)
            and parsed_url.username is None
            and parsed_url.password is None
            and not parsed_url.query
            and not parsed_url.fragment,
            "KHAL_CONFIG_INVALID",
            "KHAL base URL is invalid.",
            503,
        )
        require(timeout_seconds > 0, "KHAL_CONFIG_INVALID", "KHAL timeout must be positive.", 503)
        require(page_size > 0 and max_pages > 0, "KHAL_CONFIG_INVALID", "KHAL pagination limits must be positive.", 503)
        self.base_url = base_url.rstrip("/")
        self.credential_reference = credential_reference
        self.tenant_mapping = dict(tenant_mapping)
        self.timeout_seconds = timeout_seconds
        self.page_size = page_size
        self.max_pages = max_pages
        self.stale_after_seconds = stale_after_seconds
        self.secret_resolver = secret_resolver or EnvironmentSecretResolver()
        self._client = client
        self._clock = clock
        self._last_success: dict[str, datetime] = {}
        self._last_error_at: dict[str, datetime] = {}
        self._cache: dict[tuple[str, str, str], tuple[datetime, list[dict[str, Any]]]] = {}

    @classmethod
    def from_env(
        cls,
        *,
        client: httpx.Client | None = None,
        secret_resolver: SecretResolver | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> KHALProvider | None:
        if os.getenv("KHAL_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            return None
        raw_mapping = os.getenv("KHAL_TENANT_MAP", "{}")
        try:
            parsed_mapping = json.loads(raw_mapping)
            require(isinstance(parsed_mapping, dict), "KHAL_CONFIG_INVALID", "KHAL tenant mapping is invalid.", 503)
            mapping = {str(key): str(value) for key, value in parsed_mapping.items() if key and value}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DomainError("KHAL_CONFIG_INVALID", "KHAL tenant mapping is invalid.", 503) from exc
        default_tenant = os.getenv("KHAL_TENANT_ID", "").strip()
        if default_tenant:
            mapping.setdefault("*", default_tenant)
        return cls(
            base_url=os.getenv("KHAL_BASE_URL", ""),
            credential_reference=os.getenv(
                "KHAL_CREDENTIAL_REFERENCE", "env://KHAL_READONLY_TOKEN"
            ),
            tenant_mapping=mapping,
            timeout_seconds=float(os.getenv("KHAL_REQUEST_TIMEOUT_SECONDS", "10")),
            page_size=int(os.getenv("KHAL_PAGE_SIZE", "100")),
            max_pages=int(os.getenv("KHAL_MAX_PAGES", "100")),
            stale_after_seconds=float(os.getenv("KHAL_STALE_AFTER_SECONDS", "300")),
            secret_resolver=secret_resolver,
            client=client,
            clock=clock,
        )

    def _external_tenant(self, tenant_id: str) -> str:
        external = self.tenant_mapping.get(tenant_id) or self.tenant_mapping.get("*")
        require(
            bool(external),
            "KHAL_TENANT_NOT_MAPPED",
            "This tenant is not mapped to a KHAL tenant.",
            403,
        )
        return str(external)

    @classmethod
    def _contains_secret(cls, value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                any(part in cls._SECRET_KEYS for part in str(key).lower().replace("-", "_").split("_"))
                or cls._contains_secret(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_secret(item) for item in value)
        return False

    def _headers(self, tenant_id: str) -> dict[str, str]:
        token = self.secret_resolver.resolve(self.credential_reference)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-KHAL-Tenant-ID": self._external_tenant(tenant_id),
        }

    def _request(self, path: str, tenant_id: str, params: dict[str, Any]) -> httpx.Response:
        request = self._client.request if self._client else httpx.request
        return request(
            "GET",
            f"{self.base_url}{path}",
            headers=self._headers(tenant_id),
            params=params,
            timeout=self.timeout_seconds,
        )

    def _fetch_pages(
        self, resource: str, tenant_id: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(self.max_pages):
            page_params = {**params, "limit": self.page_size}
            if cursor:
                page_params["cursor"] = cursor
            response = self._request(f"/{resource}", tenant_id, page_params)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                page_items, next_cursor = payload, None
            elif isinstance(payload, dict):
                page_items = payload.get("items", payload.get("data", []))
                next_cursor = payload.get("next_cursor", payload.get("next"))
            else:
                raise TypeError("unexpected response")
            if not isinstance(page_items, list) or any(not isinstance(item, dict) for item in page_items):
                raise ValueError("unexpected response items")
            require(
                not self._contains_secret(page_items),
                "KHAL_RESPONSE_REJECTED",
                "KHAL returned unsafe credential-shaped data.",
                502,
            )
            items.extend(page_items)
            if not next_cursor:
                return items
            cursor = str(next_cursor)
            if cursor in seen:
                raise ValueError("pagination cycle")
            seen.add(cursor)
        raise ValueError("pagination limit exceeded")

    @staticmethod
    def _asset(item: dict[str, Any]) -> dict[str, Any]:
        external_id = item.get("external_id", item.get("id"))
        if external_id is None:
            raise ValueError("asset id missing")
        return {
            "external_id": str(external_id),
            "name": str(item.get("name", external_id)),
            "asset_type": str(item.get("asset_type", item.get("type", "UNKNOWN"))),
            "status": str(item.get("status", "UNKNOWN")),
            "metadata": deepcopy(item.get("metadata", {})),
            "provider": "KHAL",
        }

    @staticmethod
    def _metric(item: dict[str, Any]) -> dict[str, Any]:
        external_id = item.get("external_id", item.get("id"))
        if external_id is None:
            raise ValueError("metric id missing")
        return {
            "external_id": str(external_id),
            "name": str(item.get("name", external_id)),
            "unit": item.get("unit"),
            "value_type": str(item.get("value_type", item.get("type", "NUMBER"))),
            "asset_external_id": item.get("asset_external_id", item.get("asset_id")),
            "provider": "KHAL",
        }

    def _measurement(self, item: dict[str, Any]) -> dict[str, Any]:
        external_id = item.get("external_id", item.get("id", item.get("measurement_id")))
        metric_id = item.get("external_metric", item.get("metric_id", item.get("metric")))
        observed_at = item.get("observed_at", item.get("timestamp"))
        if external_id is None or metric_id is None or observed_at is None or "value" not in item:
            raise ValueError("measurement fields missing")
        source_quality = str(
            item.get("quality", item.get("data_quality", "UNKNOWN"))
        ).upper()
        return {
            "external_id": str(external_id),
            "external_metric": str(metric_id),
            "asset_external_id": item.get("asset_external_id", item.get("asset_id")),
            "value": item["value"],
            "unit": item.get("unit"),
            "observed_at": str(observed_at),
            "received_at": _iso(self._clock()),
            "quality": source_quality if source_quality in DATA_QUALITY else "UNKNOWN",
            "provenance": {
                "provider": "KHAL",
                "source": "KHAL_API",
                "external_id": str(external_id),
            },
        }

    def _read(
        self,
        resource: str,
        tenant_id: str,
        params: dict[str, Any],
        normalizer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        cache_key = (tenant_id, resource, json.dumps(params, sort_keys=True, default=str))
        now = self._clock()
        try:
            raw_items = self._fetch_pages(resource, tenant_id, params)
            normalized = [normalizer(item) for item in raw_items]
            self._cache[cache_key] = (now, deepcopy(normalized))
            self._last_success[tenant_id] = now
            self._last_error_at.pop(tenant_id, None)
            return {
                "items": normalized,
                "status": "READY",
                "read_only": True,
                "last_success_at": _iso(now),
                "stale": False,
            }
        except DomainError as exc:
            if exc.code != "KHAL_CREDENTIAL_UNAVAILABLE":
                raise
            return self._degraded(cache_key, tenant_id, resource, now)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return self._degraded(cache_key, tenant_id, resource, now)

    def _degraded(
        self,
        cache_key: tuple[str, str, str],
        tenant_id: str,
        resource: str,
        now: datetime,
    ) -> dict[str, Any]:
        self._last_error_at[tenant_id] = now
        cached = self._cache.get(cache_key)
        if cached:
            cached_at, cached_items = cached
            age = max(0.0, (now - cached_at).total_seconds())
            stale = age > self.stale_after_seconds
            items = deepcopy(cached_items)
            if stale and resource == "measurements":
                for item in items:
                    item["source_quality"] = item.get("quality", "UNKNOWN")
                    item["quality"] = "STALE"
            return {
                "items": items,
                "status": "DEGRADED",
                "read_only": True,
                "last_success_at": _iso(cached_at),
                "stale": stale,
                "age_seconds": age,
                "source": "LAST_VERIFIED_CACHE",
            }
        raise DomainError(
            "KHAL_UNAVAILABLE",
            "KHAL is unavailable and no verified cached data exists.",
            503,
        ) from None

    def assets(self, tenant_id: str) -> dict[str, Any]:
        return self._read("assets", tenant_id, {}, self._asset)

    def metrics(self, tenant_id: str) -> dict[str, Any]:
        return self._read("metrics", tenant_id, {}, self._metric)

    def measurements(self, tenant_id: str, query: dict[str, Any]) -> dict[str, Any]:
        allowed = {"external_metric", "observed_from", "observed_to"}
        require(
            not (set(query) - allowed) and not self._contains_secret(query),
            "INVALID_INPUT",
            "KHAL measurement query contains unsupported or credential fields.",
        )
        return self._read(
            "measurements",
            tenant_id,
            {key: value for key, value in query.items() if value is not None},
            self._measurement,
        )

    def readiness(self, tenant_id: str | None = None) -> dict[str, Any]:
        now = self._clock()
        last = self._last_success.get(tenant_id) if tenant_id else max(self._last_success.values(), default=None)
        last_error = self._last_error_at.get(tenant_id) if tenant_id else max(self._last_error_at.values(), default=None)
        if last is None:
            status = "OFFLINE" if last_error else "CONFIGURED"
            stale = True
        else:
            stale = (now - last).total_seconds() > self.stale_after_seconds
            status = "DEGRADED" if stale or (last_error is not None and last_error > last) else "READY"
        return {
            "provider": "KHAL",
            "configured": True,
            "enabled": True,
            "read_only": True,
            "status": status,
            "last_success_at": _iso(last) if last else None,
            "stale": stale,
        }


class ERIService:
    def __init__(
        self, repo: InMemoryRepository, khal_provider: ExternalRealityProvider | None = None
    ) -> None:
        self.repo = repo
        self.connections = repo.eri_connections
        self.metric_bindings = repo.metric_bindings
        self.khal_provider = khal_provider

    @classmethod
    def from_env(cls, repo: InMemoryRepository) -> ERIService:
        return cls(repo, KHALProvider.from_env())

    def khal_readiness(self, tenant_id: str | None = None) -> dict[str, Any]:
        if self.khal_provider is None:
            return {
                "provider": "KHAL",
                "configured": False,
                "enabled": False,
                "read_only": True,
                "status": "ADAPTER_NOT_CONFIGURED",
                "last_success_at": None,
                "stale": True,
            }
        return self.khal_provider.readiness(tenant_id)

    def khal_assets(self, tenant_id: str) -> dict[str, Any]:
        if self.khal_provider is None:
            return {
                "items": [],
                "read_only": True,
                "status": "ADAPTER_NOT_CONFIGURED",
                "contract": "A configured provider adapter supplies normalized assets.",
            }
        return self.khal_provider.assets(tenant_id)

    def khal_metrics(self, tenant_id: str) -> dict[str, Any]:
        if self.khal_provider is None:
            return {"items": [], "read_only": True, "status": "ADAPTER_NOT_CONFIGURED"}
        return self.khal_provider.metrics(tenant_id)

    def khal_measurements(self, tenant_id: str, query: dict[str, Any]) -> dict[str, Any]:
        if self.khal_provider is None:
            return {
                "items": [],
                "external_metric": query.get("external_metric"),
                "period": {"from": query.get("observed_from"), "to": query.get("observed_to")},
                "read_only": True,
                "status": "ADAPTER_NOT_CONFIGURED",
            }
        return self.khal_provider.measurements(tenant_id, query)

    def ingest_khal_measurements(
        self, project: Project, query: dict[str, Any]
    ) -> dict[str, Any]:
        response = self.khal_measurements(project.tenant_id, query)
        require(
            response["status"] != "ADAPTER_NOT_CONFIGURED",
            "KHAL_ADAPTER_NOT_CONFIGURED",
            "KHAL adapter is not configured.",
            503,
        )
        events = []
        duplicates = 0
        for measurement in response["items"]:
            event, duplicate = self.ingest_event(
                project,
                {
                    "provider": "KHAL",
                    "external_event_id": measurement["external_id"],
                    "event_type": "VALUE_MEASUREMENT",
                    "subject": {
                        "type": "ASSET",
                        "external_id": measurement.get("asset_external_id"),
                    },
                    "metric": measurement["external_metric"],
                    "observed": {
                        "value": measurement["value"],
                        "unit": measurement.get("unit"),
                    },
                    "observed_at": measurement["observed_at"],
                    "received_at": measurement["received_at"],
                    "data_quality": measurement.get("quality", "UNKNOWN"),
                    "source_provenance": measurement["provenance"],
                    "transformation_history": [
                        {
                            "operation": "KHAL_NORMALIZATION",
                            "causal_attribution": "NOT_ASSESSED",
                        }
                    ],
                },
            )
            events.append(event)
            duplicates += int(duplicate)
        return {
            "events": events,
            "duplicates": duplicates,
            "read_only_source": True,
            "provider_status": response["status"],
        }

    def providers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "KHAL",
                "levels": ["OBSERVE", "VERIFY"],
                **self.khal_readiness(),
            },
            {"name": "DOCUMENT", "levels": ["OBSERVE", "VERIFY"], "read_only": True, "configured": True},
            {"name": "MANUAL", "levels": ["OBSERVE", "VERIFY"], "read_only": True, "configured": True},
        ]

    def connect_khal(self, tenant_id: str, config: dict[str, Any]) -> dict[str, Any]:
        with self.repo.transaction():
            require(config.get("base_url"), "INVALID_INPUT", "KHAL base_url is required.")
            require(
                config.get("credential_reference"),
                "INVALID_INPUT",
                "Use a secret-manager credential reference; raw credentials are not accepted.",
            )
            forbidden = {"api_key", "token", "password", "secret"}
            require(not forbidden.intersection(config), "INVALID_INPUT", "Raw KHAL secrets must not be stored.")
            reference = str(config["credential_reference"])
            require(
                reference.startswith(("env://", "secret-manager://", "vault://")),
                "INVALID_INPUT",
                "KHAL credential_reference must identify a supported secret resolver.",
            )
            parsed_url = urlsplit(str(config["base_url"]))
            require(
                parsed_url.scheme in {"http", "https"}
                and bool(parsed_url.hostname)
                and parsed_url.username is None
                and parsed_url.password is None,
                "INVALID_INPUT",
                "KHAL base_url must not contain credentials.",
            )
            connection = {
                "id": new_id("eri"),
                "tenant_id": tenant_id,
                "provider": "KHAL",
                "base_url": config["base_url"],
                "credential_reference": config["credential_reference"],
                "read_only": True,
                "status": "CONFIGURED",
                "created_at": now_iso(),
            }
            self.connections["KHAL"] = connection
            self.repo.audit(None, "eri_provider_configured", "HUMAN", {"provider": "KHAL", "tenant_id": tenant_id})
            return deepcopy(connection)

    def ingest_event(self, project: Project, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self.repo.transaction():
            provider = str(payload.get("provider", "")).upper()
            external_id = str(payload.get("external_event_id", ""))
            require(provider in {"KHAL", "DOCUMENT", "MANUAL", "API"}, "INVALID_INPUT", "Provider is invalid.")
            require(external_id, "INVALID_INPUT", "external_event_id is required.")
            event_key = (project.tenant_id, provider, external_id)
            existing_id = self.repo.external_event_keys.get(event_key)
            if existing_id:
                return self.repo.get_resource(project, existing_id, "REALITY_EVENT").public(), True
            event_type = str(payload.get("event_type", "")).upper()
            require(event_type in EVENT_TYPES, "INVALID_INPUT", "RealityEvent type is invalid.")
            require(payload.get("observed_at"), "INVALID_INPUT", "observed_at is required.")
            quality = str(payload.get("data_quality", "UNKNOWN")).upper()
            require(quality in DATA_QUALITY, "INVALID_INPUT", "data_quality is invalid.")
            normalized = {
                "provider": provider,
                "external_event_id": external_id,
                "event_type": event_type,
                "subject": payload.get("subject", {}),
                "metric": payload.get("metric"),
                "baseline": payload.get("baseline"),
                "observed": payload.get("observed"),
                "observed_at": payload["observed_at"],
                "generated_at": payload.get("generated_at"),
                "received_at": payload.get("received_at") or now_iso(),
                "source_confidence": payload.get("source_confidence"),
                "data_quality": quality,
                "source_provenance": payload.get("source_provenance"),
                "transformation_history": payload.get("transformation_history", []),
                "status": "RECEIVED",
            }
            record = self.repo.create_resource(
                project,
                "REALITY_EVENT",
                normalized,
                status="RECEIVED",
                provenance="EXTERNAL_EVIDENCE",
            )
            self.repo.external_event_keys[event_key] = record.id
            return record.public(), False

    def create_evidence(self, project: Project, event_id: str) -> dict[str, Any]:
        with self.repo.transaction():
            event = self.repo.get_resource(project, event_id, "REALITY_EVENT")
            require(
                event.data.get("data_quality") not in {"INVALID", "MISSING"},
                "VALUE_EVIDENCE_INSUFFICIENT",
                "Invalid or missing external data cannot become Evidence.",
            )
            observed = event.data.get("observed")
            require(observed is not None, "VALUE_EVIDENCE_INSUFFICIENT", "Event has no observation.")
            statement = (
                f"{event.data.get('metric', 'Metric')} observed as "
                f"{observed.get('value') if isinstance(observed, dict) else observed}"
                f" {observed.get('unit', '') if isinstance(observed, dict) else ''}".strip()
            )
            evidence = self.repo.create_resource(
                project,
                "EVIDENCE",
                {
                    "statement": statement,
                    "source_type": "EXTERNAL_REALITY_PROVIDER",
                    "provider": event.data["provider"],
                    "reality_event_id": event.id,
                    "observed_at": event.data["observed_at"],
                    "evidence_scope": event.data.get("subject", {}),
                    "verification_status": "VERIFIED_SOURCE",
                    "attribution": "NOT_ASSESSED",
                },
                status="CANDIDATE",
                provenance="EXTERNAL_EVIDENCE",
            )
            self.repo.add_link(project, "REALITY_EVENT", event.id, "EVIDENCE", evidence.id, "OBSERVED_AS")
            event.status = "EVIDENCE_CANDIDATE"
            return evidence.public()

    def bind_metric(self, project: Project, payload: dict[str, Any]) -> dict[str, Any]:
        with self.repo.transaction():
            metric = self.repo.get_resource(project, payload.get("ctf_metric_id"), "VALUE_METRIC")
            require(payload.get("external_metric"), "INVALID_INPUT", "external_metric is required.")
            binding = {
                "id": new_id("mb"),
                "project_id": project.id,
                "ctf_metric_id": metric.id,
                "provider": str(payload.get("provider", "KHAL")).upper(),
                "external_metric": payload["external_metric"],
                "aggregation": payload.get("aggregation", "NONE"),
                "status": "CONFIRMED" if payload.get("human_confirmed") else "PROPOSED",
                "created_at": now_iso(),
            }
            self.metric_bindings[binding["id"]] = binding
            self.repo.audit(project.id, "eri_metric_bound", "HUMAN", binding)
            return deepcopy(binding)

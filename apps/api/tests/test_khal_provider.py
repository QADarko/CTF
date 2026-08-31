from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.api.app import horizontal
from packages.ctf_domain.eri import KHALProvider
from packages.ctf_domain.errors import DomainError


class StaticSecretResolver:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def resolve(self, reference: str) -> str:
        assert reference == "env://KHAL_TEST_TOKEN"
        return self.secret


def provider(
    handler,
    *,
    tenant_mapping: dict[str, str] | None = None,
    clock=None,
    stale_after_seconds: float = 300,
) -> KHALProvider:
    return KHALProvider(
        base_url="https://khal.example.test/v1",
        credential_reference="env://KHAL_TEST_TOKEN",
        tenant_mapping=tenant_mapping or {"ctf-tenant": "khal-tenant"},
        secret_resolver=StaticSecretResolver("super-secret-khal-token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock or (lambda: datetime(2026, 8, 29, tzinfo=UTC)),
        stale_after_seconds=stale_after_seconds,
        page_size=2,
    )


def test_assets_success_paginates_normalizes_and_maps_tenant():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["x-khal-tenant-id"] == "khal-tenant"
        assert request.headers["authorization"] == "Bearer super-secret-khal-token"
        assert request.extensions["timeout"]["read"] == 10
        if request.url.params.get("cursor") is None:
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "asset-1", "name": "Pump", "type": "EQUIPMENT"}],
                    "next_cursor": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={"items": [{"id": "asset-2", "name": "Tank", "type": "EQUIPMENT"}]},
        )

    result = provider(handler).assets("ctf-tenant")

    assert result["status"] == "READY"
    assert [item["external_id"] for item in result["items"]] == ["asset-1", "asset-2"]
    assert len(requests) == 2
    assert requests[1].url.params["cursor"] == "page-2"
    assert requests[0].url.params["limit"] == "2"


def test_metrics_and_measurements_are_normalized_read_only():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/metrics"):
            return httpx.Response(
                200,
                json={"items": [{"id": "energy", "name": "Energy", "unit": "kWh"}]},
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "measurement-1",
                        "metric_id": "energy",
                        "asset_id": "asset-1",
                        "value": 42,
                        "unit": "kWh",
                        "timestamp": "2026-08-29T00:00:00Z",
                        "quality": "valid",
                    }
                ]
            },
        )

    khal = provider(handler)
    metric = khal.metrics("ctf-tenant")["items"][0]
    measurement = khal.measurements(
        "ctf-tenant", {"external_metric": "energy"}
    )["items"][0]

    assert metric["provider"] == "KHAL"
    assert measurement["quality"] == "VALID"
    assert measurement["provenance"]["external_id"] == "measurement-1"
    assert not hasattr(khal, "write")
    assert not hasattr(khal, "actuate")
    assert not hasattr(khal, "command")


def test_timeout_uses_verified_cache_then_marks_it_stale():
    current = [datetime(2026, 8, 29, tzinfo=UTC)]
    offline = [False]

    def handler(_: httpx.Request) -> httpx.Response:
        if offline[0]:
            raise httpx.ReadTimeout("super-secret-khal-token")
        return httpx.Response(200, json={"items": [{"id": "asset-1", "name": "Pump"}]})

    khal = provider(
        handler,
        clock=lambda: current[0],
        stale_after_seconds=60,
    )
    assert khal.assets("ctf-tenant")["status"] == "READY"

    offline[0] = True
    current[0] += timedelta(seconds=30)
    degraded = khal.assets("ctf-tenant")
    assert degraded["status"] == "DEGRADED"
    assert degraded["source"] == "LAST_VERIFIED_CACHE"
    assert degraded["stale"] is False

    current[0] += timedelta(seconds=31)
    stale = khal.assets("ctf-tenant")
    assert stale["stale"] is True
    assert khal.readiness("ctf-tenant")["status"] == "DEGRADED"


def test_offline_without_cache_returns_safe_error_without_secret():
    secret = "super-secret-khal-token"

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret)

    khal = provider(handler)
    with pytest.raises(DomainError) as caught:
        khal.assets("ctf-tenant")

    assert caught.value.code == "KHAL_UNAVAILABLE"
    assert secret not in caught.value.message
    assert secret not in json.dumps(khal.readiness("ctf-tenant"))
    assert khal.readiness("ctf-tenant")["status"] == "OFFLINE"


def test_unmapped_tenant_is_rejected_before_network():
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"items": []})

    khal = provider(handler, tenant_mapping={"other": "external-other"})
    with pytest.raises(DomainError) as caught:
        khal.assets("ctf-tenant")

    assert caught.value.code == "KHAL_TENANT_NOT_MAPPED"
    assert calls == 0


def test_credential_shaped_provider_data_is_rejected():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"items": [{"id": "asset-1", "metadata": {"token": "leak"}}]},
        )

    with pytest.raises(DomainError) as caught:
        provider(handler).assets("ctf-tenant")

    assert caught.value.code == "KHAL_RESPONSE_REJECTED"
    assert "leak" not in caught.value.message


def test_disabled_endpoints_remain_honest_stub(client, project, monkeypatch):
    monkeypatch.setattr(horizontal.eri, "khal_provider", None)
    response = client.get("/api/v1/eri/khal/assets", headers=project["headers"])
    health = client.get("/api/v1/eri/khal/health", headers=project["headers"])

    assert response.json()["status"] == "ADAPTER_NOT_CONFIGURED"
    assert health.json()["enabled"] is False


def test_enabled_endpoint_calls_provider_and_ingestion_deduplicates(
    client, project, monkeypatch
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "measurement-1",
                        "metric_id": "energy",
                        "asset_id": "asset-1",
                        "value": 42,
                        "unit": "kWh",
                        "timestamp": "2026-08-29T00:00:00Z",
                        "quality": "VALID",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        horizontal.eri,
        "khal_provider",
        provider(handler, tenant_mapping={"*": "external-tenant"}),
    )
    path = f"/api/v1/projects/{project['project']['id']}/eri/khal/measurements/ingest"
    first = client.post(
        path,
        params={"external_metric": "energy"},
        headers=project["headers"],
    )
    second = client.post(
        path,
        params={"external_metric": "energy"},
        headers=project["headers"],
    )

    assert first.status_code == 201
    assert first.json()["duplicates"] == 0
    assert second.json()["duplicates"] == 1
    event = first.json()["events"][0]["data"]
    assert event["provider"] == "KHAL"
    assert event["external_event_id"] == "measurement-1"
    assert event["observed_at"] == "2026-08-29T00:00:00Z"
    assert event["received_at"] == "2026-08-29T00:00:00Z"
    assert event["observed"] == {"value": 42, "unit": "kWh"}
    assert event["source_provenance"]["provider"] == "KHAL"
    assert "attribution" not in event


def test_connect_rejects_raw_credentials_in_payload(client, project):
    response = client.post(
        "/api/v1/eri/providers/khal/connect",
        headers=project["headers"],
        json={
            "base_url": "https://khal.example.test",
            "credential_reference": "env://KHAL_READONLY_TOKEN",
            "token": "must-not-be-accepted",
        },
    )

    assert response.status_code == 400
    assert "must-not-be-accepted" not in response.text


def test_from_env_uses_reference_and_explicit_tenant_map(monkeypatch):
    monkeypatch.setenv("KHAL_ENABLED", "true")
    monkeypatch.setenv("KHAL_BASE_URL", "https://khal.example.test/v1")
    monkeypatch.setenv("KHAL_CREDENTIAL_REFERENCE", "env://KHAL_TEST_TOKEN")
    monkeypatch.setenv("KHAL_TENANT_MAP", '{"ctf-a":"khal-a"}')
    monkeypatch.delenv("KHAL_TENANT_ID", raising=False)

    khal = KHALProvider.from_env(secret_resolver=StaticSecretResolver("not-retained"))

    assert khal is not None
    assert khal.credential_reference == "env://KHAL_TEST_TOKEN"
    assert khal.tenant_mapping == {"ctf-a": "khal-a"}
    assert not hasattr(khal, "token")


def test_base_url_cannot_embed_credentials():
    with pytest.raises(DomainError) as caught:
        KHALProvider(
            base_url="https://raw-secret@khal.example.test",
            credential_reference="env://KHAL_TEST_TOKEN",
            tenant_mapping={"ctf": "khal"},
        )

    assert caught.value.code == "KHAL_CONFIG_INVALID"
    assert "raw-secret" not in caught.value.message

from __future__ import annotations

from packages.ctf_domain.repository import repository


def test_model_router_escalation_and_cost_ledger(client, project):
    headers = project["headers"]
    project_id = project["project"]["id"]
    route = client.post(
        "/api/v1/ai/routes/resolve",
        headers=headers,
        json={"operation": "CLASSIFICATION", "consequentiality": "CRITICAL"},
    )
    assert route.status_code == 200
    assert route.json()["tier"] == "T3"
    assert route.json()["allow_lower_capability_fallback"] is False

    usage = client.post(
        "/api/v1/ai/usage",
        headers=headers,
        json={
            "project_id": project_id,
            "operation": "RED_TEAM",
            "provider": "OPENAI",
            "model": "configured-critical-model",
            "capability": "CRITICAL_REASONING",
            "reasoning_effort": "HIGH",
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 100,
            "input_per_mtok": "10",
            "cached_input_per_mtok": "1",
            "output_per_mtok": "30",
            "price_snapshot_id": "price-2026-08",
        },
    )
    assert usage.status_code == 201
    assert usage.json()["estimated_cost_usd"] == "0.011200"
    ledger = client.get(
        f"/api/v1/projects/{project_id}/ai-cost-ledger", headers=headers
    ).json()
    assert ledger["runs"] == 1
    assert ledger["entries"][0]["price_snapshot_id"] == "price-2026-08"


def test_eri_deduplicates_normalized_events_and_preserves_attribution_boundary(
    client, project
):
    headers = project["headers"]
    project_id = project["project"]["id"]
    payload = {
        "project_id": project_id,
        "provider": "KHAL",
        "external_event_id": "KHAL-1",
        "event_type": "PERFORMANCE_DEVIATION",
        "subject": {"type": "EQUIPMENT", "external_id": "PUMP-17"},
        "metric": "energy_efficiency",
        "baseline": {"value": 0.87, "unit": "ratio"},
        "observed": {"value": 0.71, "unit": "ratio"},
        "observed_at": "2026-08-07T10:15:00Z",
        "source_confidence": 0.96,
        "data_quality": "VALID",
    }
    first = client.post("/api/v1/eri/reality-events", headers=headers, json=payload)
    second = client.post("/api/v1/eri/reality-events", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.json()["duplicate"] is True
    assert first.json()["event"]["id"] == second.json()["event"]["id"]

    evidence = client.post(
        f"/api/v1/eri/reality-events/{first.json()['event']['id']}/create-evidence",
        params={"project_id": project_id},
        headers=headers,
    )
    assert evidence.status_code == 201
    assert evidence.json()["data"]["attribution"] == "NOT_ASSESSED"
    assert evidence.json()["data"]["reality_event_id"] == first.json()["event"]["id"]


def test_khal_connection_rejects_raw_secrets_and_metric_binding_is_explicit(
    client, project
):
    headers = project["headers"]
    project_id = project["project"]["id"]
    good = client.post(
        "/api/v1/eri/providers/khal/connect",
        headers=headers,
        json={
            "base_url": "https://khal.example.invalid",
            "credential_reference": "secret-manager://ctf/khal/read-only",
        },
    )
    assert good.status_code == 201
    assert good.json()["read_only"] is True

    domain_project = repository.projects[project_id]
    metric = repository.create_resource(
        domain_project,
        "VALUE_METRIC",
        {"name": "Energy use", "unit": "kWh"},
        status="ACTIVE",
        provenance="USER",
    )
    binding = client.post(
        "/api/v1/eri/metric-bindings",
        headers=headers,
        json={
            "project_id": project_id,
            "ctf_metric_id": metric.id,
            "external_metric": "SITE-01.energy.total_kwh",
            "aggregation": "MONTHLY_SUM",
            "human_confirmed": True,
        },
    )
    assert binding.status_code == 201
    assert binding.json()["status"] == "CONFIRMED"

from __future__ import annotations

from packages.ctf_domain.state_machine import GATE_SPECS, validate_gate_decision


def test_create_alias_is_accepted_as_creation_family(client, project):
    headers = project["headers"] | {"Idempotency-Key": "create-alias"}
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "entry_family": "CREATE",
            "entry_type": "PROBLEM",
            "initial_input": "Start from a challenge.",
        },
    )
    assert response.status_code == 201
    assert response.json()["entry_family"] == "CREATION"


def test_project_creation_is_idempotent_and_tenant_safe(client, project):
    session = project["session"]
    headers = project["headers"] | {"Idempotency-Key": "same-project"}
    payload = {
        "entry_family": "FUNDING",
        "entry_type": "PLAN_TO_APPLY",
        "initial_input": "Prepare for future funding.",
        "source": {},
    }
    first = client.post("/api/v1/projects", headers=headers, json=payload)
    second = client.post("/api/v1/projects", headers=headers, json=payload)
    assert first.json()["id"] == second.json()["id"]

    other = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "other"}).json()
    denied = client.get(
        f"/api/v1/projects/{project['project']['id']}",
        headers={"X-Session-Token": other["token"]},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACCESS_DENIED"
    assert session["tenant_id"] == "public"


def test_first_three_human_gates_and_ai_authority(client, project):
    project_id = project["project"]["id"]
    headers = project["headers"]

    reality = client.post(
        f"/api/v1/projects/{project_id}/resources/REALITY",
        headers=headers,
        json={"data": {"items": [{"text": "Churn increased.", "provenance": "USER"}]}},
    )
    assert reality.status_code == 201
    current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()

    blocked = client.post(
        f"/api/v1/projects/{project_id}/gates/{current['active_gate']['id']}/decision",
        headers=headers,
        json={"decision": "CONFIRM", "actor_type": "AI"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "HUMAN_AUTHORITY_REQUIRED"

    confirmed = client.post(
        f"/api/v1/projects/{project_id}/gates/{current['active_gate']['id']}/decision",
        headers=headers | {"Idempotency-Key": "gate-1"},
        json={"decision": "CONFIRM", "expected_version": current["version"]},
    )
    assert confirmed.json()["project_stage"] == "QUESTION"
    duplicate = client.post(
        f"/api/v1/projects/{project_id}/gates/{current['active_gate']['id']}/decision",
        headers=headers | {"Idempotency-Key": "gate-1"},
        json={"decision": "CONFIRM"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    client.post(
        f"/api/v1/projects/{project_id}/resources/QUESTION",
        headers=headers,
        json={"data": {"text": "What drives avoidable churn?"}},
    )
    current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    gate2 = client.post(
        f"/api/v1/projects/{project_id}/gates/{current['active_gate']['id']}/decision",
        headers=headers,
        json={"decision": "CUSTOM"},
    )
    assert gate2.json()["project_stage"] == "PERCEPTION"

    client.post(
        f"/api/v1/projects/{project_id}/resources/PERCEPTION",
        headers=headers,
        json={"data": {"from": "Price is the cause", "to": "Price may be one factor"}},
    )
    current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    gate3 = client.post(
        f"/api/v1/projects/{project_id}/gates/{current['active_gate']['id']}/decision",
        headers=headers,
        json={"decision": "PARTIAL"},
    )
    assert gate3.json()["project_stage"] == "EVIDENCE"


def test_all_nineteen_gates_are_declared_and_validate_stage():
    assert set(GATE_SPECS) == set(range(1, 20))
    for number, spec in GATE_SPECS.items():
        accepted = next(iter(spec.accepted))
        stage, _, advances = validate_gate_decision(number, spec.stage, accepted)
        assert stage == spec.next_stage
        assert advances is True


def test_optimistic_lock_and_memory_authority(client, project):
    project_id = project["project"]["id"]
    headers = project["headers"]
    version = project["project"]["version"]
    first = client.post(
        f"/api/v1/projects/{project_id}/memory/operations",
        headers=headers,
        json={
            "expected_version": version,
            "operations": [{"op": "UPDATE", "path": "reality", "value": {"confirmed": True}}],
        },
    )
    assert first.status_code == 201
    stale = client.post(
        f"/api/v1/projects/{project_id}/memory/operations",
        headers=headers,
        json={
            "expected_version": version,
            "operations": [{"op": "UPDATE", "path": "question", "value": {"text": "stale"}}],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STATE_CONFLICT"

    current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    ai_overwrite = client.post(
        f"/api/v1/projects/{project_id}/memory/operations",
        headers=headers,
        json={
            "expected_version": current["version"],
            "actor_type": "AI",
            "operations": [{"op": "UPDATE", "path": "reality", "value": {"confirmed": False}}],
        },
    )
    assert ai_overwrite.status_code == 403

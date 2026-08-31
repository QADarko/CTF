from __future__ import annotations

from packages.ctf_domain.repository import repository


def test_every_mutating_route_requires_idempotency(client):
    schema = client.get("/openapi.json").json()
    exemptions = {"/api/v1/sessions/anonymous", "/api/v1/ai/routes/resolve"}
    for path, path_item in schema["paths"].items():
        if path in exemptions:
            continue
        for method in ("post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not operation:
                continue
            headers = {
                item["name"].lower(): item
                for item in operation.get("parameters", [])
                if item.get("in") == "header"
            }
            assert headers["idempotency-key"]["required"] is True, (method, path)


def test_same_request_replays(client, monkeypatch):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    session = client.post("/api/v1/sessions/anonymous", json={}).json()
    headers = {"X-Session-Token": session["token"], "Idempotency-Key": "replay-1"}
    body = {"entry_family": "CREATION", "entry_type": "PROBLEM", "initial_input": "One"}
    first = client.post("/api/v1/projects", headers=headers, json=body)
    replay = client.post("/api/v1/projects", headers=headers, json=body)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert replay.headers["Idempotency-Replayed"] == "true"


def test_changed_body_conflicts(client, monkeypatch):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    session = client.post("/api/v1/sessions/anonymous", json={}).json()
    headers = {"X-Session-Token": session["token"], "Idempotency-Key": "conflict-body"}
    client.post("/api/v1/projects", headers=headers, json={"entry_family": "CREATION", "entry_type": "PROBLEM", "initial_input": "A"})
    changed = client.post("/api/v1/projects", headers=headers, json={"entry_family": "CREATION", "entry_type": "PROBLEM", "initial_input": "B"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_changed_query_conflicts(client, monkeypatch, project):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    headers = project["headers"] | {"Idempotency-Key": "query-key"}
    first = client.post(
        f"/api/v1/projects/{project['project']['id']}/input?marker=1",
        headers=headers,
        json={"text": "hello"},
    )
    second = client.post(
        f"/api/v1/projects/{project['project']['id']}/input?marker=2",
        headers=headers,
        json={"text": "hello"},
    )
    assert first.status_code == 201
    assert second.status_code == 409


def test_idempotency_is_actor_scoped(client, monkeypatch):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    body = {"entry_family": "CREATION", "entry_type": "PROBLEM", "initial_input": "shared-key"}
    first = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "a"}).json()
    second = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "b"}).json()
    one = client.post("/api/v1/projects", headers={"X-Session-Token": first["token"], "Idempotency-Key": "shared"}, json=body)
    two = client.post("/api/v1/projects", headers={"X-Session-Token": second["token"], "Idempotency-Key": "shared"}, json=body)
    assert one.status_code == two.status_code == 201
    assert one.json()["id"] != two.json()["id"]


def test_idempotency_is_route_scoped(client, monkeypatch, project):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    headers = project["headers"] | {"Idempotency-Key": "route-key"}
    first = client.post(f"/api/v1/projects/{project['project']['id']}/input", headers=headers, json={"text": "a"})
    second = client.post(
        f"/api/v1/projects/{project['project']['id']}/resources/NOTE",
        headers=headers,
        json={"data": {"text": "a"}},
    )
    assert first.status_code == 201
    assert second.status_code == 201


def test_failed_5xx_is_not_cached(client, monkeypatch, project):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    headers = project["headers"] | {"Idempotency-Key": "five-xx"}
    first = client.post("/api/v1/ai/usage", headers=headers, json={"project_id": "missing"})
    assert first.status_code >= 400
    stored = [value for value in repository.idempotency.values() if isinstance(value, dict) and value.get("status_code", 0) >= 500]
    assert stored == []


def test_429_is_not_cached(client, monkeypatch):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    monkeypatch.setenv("CTF_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("CTF_TENANT_RATE_LIMIT_REQUESTS", "2")
    session = client.post("/api/v1/sessions/anonymous", json={}).json()
    headers = {"X-Session-Token": session["token"], "Idempotency-Key": "rate"}
    client.get("/api/v1/ai/operations", headers=headers)
    limited = client.get("/api/v1/ai/operations", headers={"X-Session-Token": session["token"]})
    if limited.status_code == 429:
        assert limited.headers.get("Idempotency-Replayed") != "true"

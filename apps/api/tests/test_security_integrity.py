from __future__ import annotations

from io import BytesIO

from packages.ctf_domain.repository import repository


def _new_project(client, tenant: str = "tenant-a"):
    session = client.post("/api/v1/sessions/anonymous", json={"tenant_id": tenant}).json()
    headers = {"X-Session-Token": session["token"]}
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "entry_family": "CREATION",
            "entry_type": "PROBLEM",
            "initial_input": "Security test",
        },
    ).json()
    return session, headers, project


def test_required_idempotency_replay_and_payload_conflict(client, monkeypatch):
    monkeypatch.setenv("CTF_IDEMPOTENCY_POLICY", "required")
    session = client.post("/api/v1/sessions/anonymous", json={}).json()
    headers = {"X-Session-Token": session["token"]}
    body = {
        "entry_family": "CREATION",
        "entry_type": "PROBLEM",
        "initial_input": "One",
    }
    missing = client.post("/api/v1/projects", headers=headers, json=body)
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    keyed = headers | {"Idempotency-Key": "project-one"}
    first = client.post("/api/v1/projects", headers=keyed, json=body)
    replay = client.post("/api/v1/projects", headers=keyed, json=body)
    assert replay.status_code == first.status_code == 201
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"

    changed = client.post(
        "/api/v1/projects", headers=keyed, json={**body, "initial_input": "Two"}
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_generated_openapi_covers_every_consequential_mutation(client):
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
            assert "429" in operation["responses"]
            assert "413" in operation["responses"]


def test_confirmed_resource_denies_patch_and_can_be_superseded(client, project):
    project_id = project["project"]["id"]
    aggregate = repository.projects[project_id]
    with repository.transaction():
        old = repository.create_resource(
            aggregate,
            "REALITY_SNAPSHOT",
            {"label": "R1", "dimensions": []},
            status="CONFIRMED",
            immutable=True,
        )

    denied = client.patch(
        f"/api/v1/projects/{project_id}/resources/REALITY_SNAPSHOT/{old.id}",
        headers=project["headers"],
        json={"data": {"label": "tampered"}},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "IMMUTABLE_RECORD"

    replacement = client.post(
        f"/api/v1/projects/{project_id}/resources/REALITY_SNAPSHOT/{old.id}/supersede",
        headers=project["headers"],
        json={"data": {"label": "R2", "dimensions": []}},
    )
    assert replacement.status_code == 201
    assert replacement.json()["supersedes_id"] == old.id
    preserved = client.get(
        f"/api/v1/projects/{project_id}/resources/REALITY_SNAPSHOT/{old.id}",
        headers=project["headers"],
    ).json()
    assert preserved["data"]["label"] == "R1"
    assert preserved["superseded_by"] == replacement.json()["id"]


def test_rate_limit_and_quota_return_shared_429_contract(client, monkeypatch):
    monkeypatch.setenv("CTF_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("CTF_RATE_LIMIT_WINDOW_SECONDS", "60")
    _, headers, project = _new_project(client)
    limited = client.get(f"/api/v1/projects/{project['id']}", headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(limited.headers["Retry-After"]) > 0

    repository.reset()
    monkeypatch.setenv("CTF_RATE_LIMIT_REQUESTS", "600")
    monkeypatch.setenv("CTF_AI_DAILY_TOKEN_QUOTA", "1")
    from apps.api.app import horizontal
    from packages.ctf_domain.ai_runtime import FakeProvider

    monkeypatch.setattr(horizontal.ai_execution, "provider", FakeProvider(fixture_mode=True))
    _, headers, project = _new_project(client)
    quota = client.post(
        f"/api/v1/projects/{project['id']}/ai/execute",
        headers=headers,
        json={"operation": "REALITY_UPDATE", "user_input": "test"},
    )
    assert quota.status_code == 429
    assert quota.json()["error"]["code"] == "AI_QUOTA_EXCEEDED"
    assert int(quota.headers["Retry-After"]) > 0


def test_filename_sanitization_malware_quarantine_and_bounds(client, project, monkeypatch):
    project_id = project["project"]["id"]
    monkeypatch.setenv("CTF_MALWARE_SCANNER", "noop")
    upload_headers = project["headers"] | {"Idempotency-Key": "clean-upload"}
    upload = client.post(
        f"/api/v1/projects/{project_id}/attachments",
        headers=upload_headers,
        files={"file": ("../../safe<>name.txt", b"clean", "text/plain")},
    )
    assert upload.status_code == 201
    assert upload.json()["data"]["original_filename"] == "safe_name.txt"
    assert upload.json()["data"]["malware_scan"]["status"] == "CLEAN"
    replay = client.post(
        f"/api/v1/projects/{project_id}/attachments",
        headers=upload_headers,
        files={"file": ("../../safe<>name.txt", b"clean", "text/plain")},
    )
    assert replay.json()["id"] == upload.json()["id"]
    assert replay.headers["Idempotency-Replayed"] == "true"

    monkeypatch.setenv("CTF_MALWARE_SCANNER", "eicar-test")
    infected = client.post(
        f"/api/v1/projects/{project_id}/attachments",
        headers=project["headers"],
        files={
            "file": (
                "eicar.txt",
                b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
                "text/plain",
            )
        },
    )
    assert infected.status_code == 422
    attachments = client.get(
        f"/api/v1/projects/{project_id}/attachments", headers=project["headers"]
    ).json()
    assert any(item["status"] == "QUARANTINED" for item in attachments)

    monkeypatch.setenv("CTF_MAX_REQUEST_BODY_BYTES", "8")
    too_large = client.post(
        f"/api/v1/projects/{project_id}/input",
        headers=project["headers"],
        json={"text": "this body is too large"},
    )
    assert too_large.status_code == 413
    assert too_large.headers["X-Content-Type-Options"] == "nosniff"


def test_download_is_tenant_safe_streaming_and_presigned(client, monkeypatch):
    _, headers_a, project_a = _new_project(client, "a")
    _, headers_b, project_b = _new_project(client, "b")
    upload = client.post(
        f"/api/v1/projects/{project_a['id']}/attachments",
        headers=headers_a,
        files={"file": ("report.txt", b"private bytes", "text/plain")},
    ).json()
    download_path = (
        f"/api/v1/projects/{project_a['id']}/attachments/{upload['id']}/download"
    )
    denied = client.get(download_path, headers=headers_b)
    assert denied.status_code == 403
    streamed = client.get(download_path, headers=headers_a)
    assert streamed.status_code == 200
    assert streamed.content == b"private bytes"

    class PresigningStore:
        backend = "s3"

        def presign_get(self, key: str, expires_seconds: int) -> str:
            assert key == upload["data"]["object_key"]
            assert expires_seconds <= 900
            return "https://objects.invalid/signed"

        def open_stream(self, key: str) -> BytesIO:
            raise AssertionError(f"unexpected local read: {key}")

    from apps.api.app import common

    monkeypatch.setattr(common, "object_store", PresigningStore())
    presigned = client.get(download_path, headers=headers_a)
    assert presigned.status_code == 200
    assert presigned.json()["url"] == "https://objects.invalid/signed"
    assert project_b["tenant_id"] == "b"

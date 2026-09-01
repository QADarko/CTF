from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from packages.ctf_domain.repository import repository

INTEGRATION_MARKERS = frozenset(
    {"integration", "postgres", "minio", "worker", "backup_restore", "ollama"}
)


def pytest_collection_modifyitems(config, items):
    del config
    for item in items:
        names = {marker.name for marker in item.iter_markers()}
        if not names.intersection(INTEGRATION_MARKERS | {"unit"}):
            item.add_marker(pytest.mark.unit)


def pytest_collection_finish(session):
    if not (os.getenv("CI") or os.getenv("CTF_REQUIRE_INTEGRATION")):
        return
    names: set[str] = set()
    for item in session.items:
        names.update(marker.name for marker in item.iter_markers())
    if "postgres" in names and not os.getenv("CTF_TEST_POSTGRES_URL"):
        pytest.exit("PostgreSQL is required for the selected integration tests.", returncode=1)
    if "minio" in names and (
        os.getenv("CTF_OBJECT_STORE", "local") not in {"minio", "s3"} or not os.getenv("S3_ENDPOINT")
    ):
        pytest.exit("MinIO is required for the selected integration tests.", returncode=1)
    if "worker" in names and not os.getenv("CTF_LIVE_WORKER_TEST"):
        pytest.exit("A live worker is required for the selected integration tests.", returncode=1)


@pytest.fixture(autouse=True)
def clean_repository():
    repository.reset()
    yield
    repository.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def project(client: TestClient) -> dict:
    session = client.post("/api/v1/sessions/anonymous", json={}).json()
    headers = {"X-Session-Token": session["token"]}
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "entry_family": "CREATION",
            "entry_type": "PROBLEM",
            "initial_input": "We need to understand customer churn.",
            "source": {"book": "iskra", "campaign": "test"},
        },
    )
    assert response.status_code == 201
    return {"session": session, "headers": headers, "project": response.json()}

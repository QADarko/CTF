from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from packages.ctf_domain.repository import repository


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

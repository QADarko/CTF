from __future__ import annotations

import pytest

from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.repository import repository
from packages.ctf_domain.resource_policy import CRITICAL_IMMUTABLE_KINDS
from packages.ctf_domain.service import CTFService

KINDS = [
    "REALITY",
    "QUESTION",
    "PERCEPTION",
    "CLAIM",
    "EVIDENCE",
    "OPPORTUNITY",
    "SPARK",
    "IDEA",
    "ASSUMPTION",
    "VALUE_BOUNDARY",
    "COMMITMENT",
    "ROADMAP",
    "BASELINE",
    "REALIZED_VALUE",
    "TRANSFORMATION",
    "REALITY_SNAPSHOT",
    "CREATION_CYCLE",
]


@pytest.mark.parametrize("kind", KINDS)
def test_confirmed_resource_cannot_patch(kind, client, project):
    project_id = project["project"]["id"]
    aggregate = repository.projects[project_id]
    data = {"statement": "locked", "name": "locked", "text": "locked", "what": "locked"}
    if kind == "EVIDENCE":
        data = {"statement": "locked evidence"}
    record = repository.create_resource(aggregate, kind, data, status="CONFIRMED", immutable=True)
    denied = client.patch(
        f"/api/v1/projects/{project_id}/resources/{kind}/{record.id}",
        headers=project["headers"],
        json={"data": {"name": "tampered"}},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "IMMUTABLE_RECORD"


@pytest.mark.parametrize("kind", ["REALITY"])
def test_confirmed_resource_can_be_superseded(kind, client, project):
    project_id = project["project"]["id"]
    aggregate = repository.projects[project_id]
    old = repository.create_resource(
        aggregate, kind, {"name": "old", "text": "old", "what": "old", "statement": "old"}, status="CONFIRMED", immutable=True
    )
    replacement = client.post(
        f"/api/v1/projects/{project_id}/resources/{kind}/{old.id}/supersede",
        headers=project["headers"],
        json={"data": {"name": "new", "text": "new", "what": "new", "statement": "new"}},
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["supersedes_id"] == old.id


def test_supersession_preserves_old_record(client, project):
    project_id = project["project"]["id"]
    aggregate = repository.projects[project_id]
    old = repository.create_resource(aggregate, "REALITY", {"text": "R0"}, status="CONFIRMED", immutable=True)
    client.post(
        f"/api/v1/projects/{project_id}/resources/REALITY/{old.id}/supersede",
        headers=project["headers"],
        json={"data": {"text": "R0-next"}},
    )
    preserved = client.get(
        f"/api/v1/projects/{project_id}/resources/REALITY/{old.id}",
        headers=project["headers"],
    ).json()
    assert preserved["id"] == old.id
    assert preserved["data"]["text"] == "R0"


def test_supersession_creates_genealogy_link(client, project):
    project_id = project["project"]["id"]
    aggregate = repository.projects[project_id]
    old = repository.create_resource(aggregate, "REALITY", {"text": "A"}, status="CONFIRMED", immutable=True)
    replacement = client.post(
        f"/api/v1/projects/{project_id}/resources/REALITY/{old.id}/supersede",
        headers=project["headers"],
        json={"data": {"text": "B"}},
    ).json()
    assert any(
        link["from_id"] == old.id and link["to_id"] == replacement["id"]
        for link in repository.creation_links
    )


def test_ai_cannot_confirm_resource(client, project):
    project_id = project["project"]["id"]
    aggregate = repository.projects[project_id]
    record = repository.create_resource(aggregate, "IDEA", {"name": "x", "what": "y"}, status="PROPOSED")
    response = client.post(
        f"/api/v1/projects/{project_id}/resources/IDEA/{record.id}/confirm",
        headers=project["headers"],
        json={"actor_type": "AI"},
    )
    assert response.status_code in {403, 422}


def test_system_cannot_overwrite_human_confirmed_record():
    from packages.ctf_domain.repository import InMemoryRepository

    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    record = repo.create_resource(project, "ROADMAP", {"name": "plan"}, status="CONFIRMED", immutable=True)
    with pytest.raises(DomainError) as caught:
        repo.update_resource(project, record.id, {"name": "overwrite"}, None)
    assert caught.value.code == "IMMUTABLE_RECORD"
    assert CRITICAL_IMMUTABLE_KINDS
    CTFService(repo)

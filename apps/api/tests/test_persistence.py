from __future__ import annotations

from pathlib import Path

import pytest

from packages.ctf_domain.object_store import LocalObjectStore
from packages.ctf_domain.repository import SQLAlchemySnapshotRepository


def test_sqlite_repository_restores_complete_state_after_restart(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    first = SQLAlchemySnapshotRepository(database_url)
    session = first.create_session("tenant-a")
    with first.transaction():
        created_project = first.create_project(
            session,
            "CREATION",
            "PROBLEM",
            "Durably understand customer churn.",
            {"source": "test"},
        )
        project = first.projects[created_project.id]
        source = first.create_resource(project, "CLAIM", {"text": "Churn increased."})
        evidence = first.create_resource(
            project, "EVIDENCE", {"statement": "Measured churn increased."}
        )
        first.add_link(project, "CLAIM", source.id, "EVIDENCE", evidence.id, "SUPPORTS")
        project.memory["claims"].append({"id": source.id})
        first.snapshot_memory(project, [{"op": "ADD", "path": "claims"}])
        first.idempotent_put("scope", session.id, "request-1", {"project_id": project.id})
        first.external_event_keys[("tenant-a", "API", "event-1")] = evidence.id
        first.cost_entries.append(
            {
                "id": "air_test",
                "project_id": project.id,
                "operation": "TEST",
                "estimated_cost_usd": "0.010000",
            }
        )
        first.ai_runs.append(
            {
                "id": "airun_test",
                "project_id": project.id,
                "operation": "REALITY_UPDATE",
                "outcome": "SUCCEEDED",
            }
        )
        first.eri_connections["KHAL"] = {"tenant_id": "tenant-a", "read_only": True}
        first.metric_bindings["mb_test"] = {"project_id": project.id}
        first.persist()
    token = session.token
    project_id = project.id
    first.close()

    restarted = SQLAlchemySnapshotRepository(database_url)
    restored_session = restarted.session_from_token(token)
    restored_project = restarted.project_for(project_id, restored_session)

    assert restored_project.memory["claims"] == [{"id": source.id}]
    assert restarted.project_resources[project_id] == [source.id, evidence.id]
    assert restarted.memory_versions[project_id][-1].operations[0]["path"] == "claims"
    assert restarted.creation_links[0]["from_id"] == source.id
    assert restarted.audit_events
    assert restarted.idempotent_get("scope", session.id, "request-1") == {
        "project_id": project_id
    }
    assert restarted.external_event_keys[("tenant-a", "API", "event-1")] == evidence.id
    assert restarted.cost_entries[0]["id"] == "air_test"
    assert restarted.ai_runs[0]["id"] == "airun_test"
    assert restarted.eri_connections["KHAL"]["read_only"] is True
    assert restarted.metric_bindings["mb_test"]["project_id"] == project_id
    restarted.close()


def test_persistent_transaction_rolls_back_memory_and_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'rollback.db'}"
    repository = SQLAlchemySnapshotRepository(database_url)
    session = repository.create_session()

    with pytest.raises(RuntimeError), repository.transaction():
        repository.create_project(
            session, "CREATION", "PROBLEM", "This must roll back.", {}
        )
        raise RuntimeError("fail transaction")

    assert repository.projects == {}
    repository.close()
    restarted = SQLAlchemySnapshotRepository(database_url)
    assert restarted.projects == {}
    assert restarted.session_from_token(session.token).id == session.id
    restarted.close()


def test_local_object_store_round_trip_and_delete(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    key = "tenant/project/random-object.pdf"
    content = b"%PDF-private-content"

    store.put(key, content, "application/pdf")
    assert store.get(key) == content
    store.delete(key)
    assert not (tmp_path / "objects" / key).exists()


def test_local_object_store_rejects_path_escape(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    with pytest.raises(ValueError):
        store.put("../public.txt", b"no", "text/plain")

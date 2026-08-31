from __future__ import annotations

import os

import pytest

from packages.ctf_domain.repository import SQLAlchemySnapshotRepository

pytestmark = pytest.mark.skipif(
    not os.getenv("CTF_TEST_POSTGRES_URL"),
    reason="Set CTF_TEST_POSTGRES_URL to run PostgreSQL integration tests.",
)


def test_postgres_roundtrip_and_rollback():
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("tenant-pg")
    with repo.transaction():
        project = repo.create_project(session, "CREATION", "PROBLEM", "pg", {})
        live = repo.projects[project.id]
        repo.create_resource(live, "REALITY", {"text": "R0"}, status="CONFIRMED")
        repo.ai_runs.append({"id": "airun_pg", "project_id": live.id, "operation": "REALITY_UPDATE"})
        repo.cost_entries.append({"id": "air_pg", "project_id": live.id, "estimated_cost_usd": "0.1"})
        repo.add_link(live, "REALITY", repo.list_resources(live, "REALITY")[0].id, "REALITY", repo.list_resources(live, "REALITY")[0].id, "SELF")
        repo.idempotent_put("pg", session.id, "k1", {"ok": True})
    project_id = project.id
    token = session.token
    repo.close()

    restarted = SQLAlchemySnapshotRepository(url)
    restored = restarted.project_for(project_id, restarted.session_from_token(token))
    assert restarted.list_resources(restored, "REALITY")
    assert restarted.ai_runs
    assert restarted.cost_entries
    assert restarted.idempotent_get("pg", session.id, "k1") == {"ok": True}
    assert restarted.creation_links
    with pytest.raises(RuntimeError), restarted.transaction():
        restarted.create_resource(restored, "QUESTION", {"text": "partial"})
        raise RuntimeError("boom")
    assert restarted.list_resources(restored, "QUESTION") == []
    restarted.close()


def test_postgres_restart_reads_project():
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("tenant-pg2")
    project = repo.create_project(session, "CREATION", "PROBLEM", "persist", {})
    project_id = project.id
    token = session.token
    repo.close()
    restarted = SQLAlchemySnapshotRepository(url)
    restored = restarted.project_for(project_id, restarted.session_from_token(token))
    assert restored.id == project_id
    assert restored.initial_input == "persist"
    restarted.close()


def test_postgres_idempotency_and_genealogy_and_ai_persist():
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("tenant-pg3")
    project = repo.create_project(session, "CREATION", "PROBLEM", "ledger", {})
    live = repo.projects[project.id]
    r0 = repo.create_resource(live, "REALITY", {"text": "R0"}, status="CONFIRMED")
    snap = repo.create_resource(live, "REALITY_SNAPSHOT", {"label": "R1"}, status="CONFIRMED")
    repo.add_link(live, "REALITY", r0.id, "REALITY_SNAPSHOT", snap.id, "SUPERSEDES")
    repo.idempotent_put("route", session.id, "gate", {"status": 200})
    repo.ai_runs.append({"id": "airun_2", "project_id": live.id, "operation": "R1_GENERATION", "outcome": "SUCCEEDED"})
    repo.cost_entries.append({"id": "cost_2", "project_id": live.id, "estimated_cost_usd": "0.2"})
    repo.persist()
    repo.close()
    restarted = SQLAlchemySnapshotRepository(url)
    assert restarted.idempotent_get("route", session.id, "gate") == {"status": 200}
    assert any(item["operation"] == "R1_GENERATION" for item in restarted.ai_runs)
    assert restarted.cost_entries
    assert any(link["relation"] == "SUPERSEDES" for link in restarted.creation_links)
    restarted.close()

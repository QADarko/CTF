from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from packages.ctf_domain.backup import dump_postgres, recreate_postgres_database, restore_postgres
from packages.ctf_domain.repository import SQLAlchemySnapshotRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.getenv("CTF_TEST_POSTGRES_URL") or shutil.which("pg_dump") is None or shutil.which("psql") is None,
        reason="PostgreSQL URL and pg_dump/psql are required for live dump/restore tests.",
    ),
]


def test_real_pg_dump_created(tmp_path: Path):
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("dump-tenant")
    project = repo.create_project(session, "CREATION", "PROBLEM", "dump", {})
    live = repo.projects[project.id]
    repo.create_resource(live, "REALITY", {"text": "R0-dump"}, status="CONFIRMED")
    repo.persist()
    dump = dump_postgres(url, tmp_path / "ctf.sql")
    assert dump.is_file()
    assert dump.stat().st_size > 0
    assert b"snapshot-placeholder" not in dump.read_bytes()
    assert "CREATE TABLE" in dump.read_text(encoding="utf-8", errors="ignore") or dump.stat().st_size > 100
    repo.close()


def test_database_can_be_destroyed():
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("destroy-tenant")
    repo.create_project(session, "CREATION", "PROBLEM", "destroy", {})
    repo.persist()
    repo.close()
    recreate_postgres_database(url)
    restarted = SQLAlchemySnapshotRepository(url)
    assert not restarted.projects
    restarted.close()


def test_real_psql_restore_succeeds(tmp_path: Path):
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("restore-tenant")
    project = repo.create_project(session, "CREATION", "PROBLEM", "restore", {})
    live = repo.projects[project.id]
    repo.create_resource(live, "REALITY", {"text": "R0-restore"}, status="CONFIRMED")
    repo.persist()
    dump = dump_postgres(url, tmp_path / "ctf.sql")
    original_id = project.id
    repo.close()
    recreate_postgres_database(url)
    restore_postgres(url, dump)
    restored = SQLAlchemySnapshotRepository(url)
    assert original_id in restored.projects
    restored.close()


def test_restored_database_matches_original(tmp_path: Path):
    url = os.environ["CTF_TEST_POSTGRES_URL"]
    repo = SQLAlchemySnapshotRepository(url)
    repo.reset()
    session = repo.create_session("match-tenant")
    project = repo.create_project(session, "CREATION", "PROBLEM", "match", {})
    live = repo.projects[project.id]
    reality = repo.create_resource(live, "REALITY", {"text": "original-r0"}, status="CONFIRMED")
    repo.persist()
    dump = dump_postgres(url, tmp_path / "ctf.sql")
    project_id = project.id
    reality_id = reality.id
    repo.close()
    recreate_postgres_database(url)
    restore_postgres(url, dump)
    restored = SQLAlchemySnapshotRepository(url)
    live = restored.projects[project_id]
    records = restored.list_resources(live, "REALITY")
    assert records
    assert records[0].id == reality_id
    assert records[0].data["text"] == "original-r0"
    restored.close()

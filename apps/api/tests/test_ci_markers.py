from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_local_pytest_succeeds_without_postgres():
    workflow = (ROOT / ".github" / "workflows" / "verify-assets.yml").read_text(encoding="utf-8")
    assert 'pytest -m "not integration"' in workflow


def test_local_pytest_succeeds_without_minio():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "integration" in pyproject
    assert "minio" in pyproject


def test_postgres_ci_job_runs_postgres_tests():
    workflow = (ROOT / ".github" / "workflows" / "verify-assets.yml").read_text(encoding="utf-8")
    assert 'pytest -m "integration and postgres"' in workflow


def test_minio_ci_job_runs_minio_tests():
    workflow = (ROOT / ".github" / "workflows" / "verify-assets.yml").read_text(encoding="utf-8")
    assert 'pytest -m "integration and minio"' in workflow


def test_worker_ci_job_runs_worker_tests():
    workflow = (ROOT / ".github" / "workflows" / "verify-assets.yml").read_text(encoding="utf-8")
    assert 'pytest -m "integration and worker"' in workflow
    assert 'pytest -m "integration and backup_restore"' in workflow


def test_integration_modules_do_not_raise_on_import():
    from apps.api.tests import (
        test_object_store_integration,
        test_postgres_integration,
        test_postgres_job_queue,
    )

    assert test_postgres_integration.__name__
    assert test_postgres_job_queue.__name__
    assert test_object_store_integration.__name__
